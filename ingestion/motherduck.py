import duckdb
import os
import pyarrow as pa
from datetime import datetime

class ArrowTableLoadingBuffer:
    def __init__(
        self,
        duckdb_schema: str,
        pyarrow_schema: pa.Schema,
        database_name: str,
        table_name: str,
        dryrun: bool = False,
        destination="local",
    ):
        self.duckdb_schema = duckdb_schema
        self.pyarrow_schema = pyarrow_schema
        self.dryrun = dryrun
        self.database_name = database_name
        self.table_name = table_name 
        self.accumulated_data = pa.Table.from_batches([], schema=pyarrow_schema)
        self.total_inserted = 0
        self.conn = self.initialize_connection(destination, duckdb_schema)
        self.primary_key_exists = "PRIMARY KEY" in duckdb_schema.upper()

    def initialize_connection(self, destination, sql):
        if destination == "md":
            print("Connecting to MotherDuck...")
            if not os.environ.get("motherduck_token"):
                raise ValueError(
                    "MotherDuck token is required. Set the environment variable 'MOTHERDUCK_TOKEN'."
                )
            conn = duckdb.connect("md:")
            conn.execute(f"USE {self.database_name}")
            if not self.dryrun:
                print(f"Creating database {self.database_name} if it doesn't exist")
                conn.execute(f"CREATE DATABASE IF NOT EXISTS {self.database_name}")
        else:
            conn = duckdb.connect(database=f"{self.database_name}.db")
        if not self.dryrun:
            print(sql)
            conn.execute(sql)
        return conn

    def insert(self, table: pa.Table) -> None:
        self.accumulated_data = pa.concat_tables([self.accumulated_data, table])
        self.flush_if_needed()

    def flush_if_needed(self):
        if self.accumulated_data.num_rows >= 10000:
            self.flush()

    def flush(self) -> None:
        if not self.dryrun and self.accumulated_data.num_rows > 0:
            self.conn.register("buffer_table", self.accumulated_data)
            if self.primary_key_exists:
                insert_query = f"""
                INSERT OR REPLACE INTO {self.table_name} SELECT * FROM buffer_table
                """
            else:
                insert_query = f"INSERT INTO {self.table_name} SELECT * FROM buffer_table"
            self.conn.execute(insert_query)
            self.conn.unregister("buffer_table")
            self.total_inserted += self.accumulated_data.num_rows
            print(f"Flushed {self.accumulated_data.num_rows} records to the database.")
            self.accumulated_data = pa.Table.from_batches([], schema=self.accumulated_data.schema)