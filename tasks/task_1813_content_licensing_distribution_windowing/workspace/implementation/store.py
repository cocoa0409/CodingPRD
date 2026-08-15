"""In-memory data store. The store starts EMPTY on every boot — no seeding."""
from util import CLOCK, new_id

TABLES = (
    "titles",
    "holders",
    "platforms",
    "slots",
    "packages",
    "licenses",
    "batches",
    "notices",
    "reports",
    "statements",
)


class Store:
    def __init__(self):
        self.tables = {name: {} for name in TABLES}
        self._seq = 0

    def insert(self, table: str, record: dict) -> dict:
        self._seq += 1
        record["id"] = new_id()
        record["_seq"] = self._seq
        record["created_at"] = CLOCK.now()
        record["updated_at"] = CLOCK.now()
        record["version"] = 1
        self.tables[table][record["id"]] = record
        return record

    def get(self, table: str, rec_id: str):
        return self.tables[table].get(rec_id)

    def all(self, table: str):
        """All records in created_at ASC order (ties by insertion sequence)."""
        return sorted(
            self.tables[table].values(), key=lambda r: (r["created_at"], r["_seq"])
        )


def mutate(record: dict):
    """Apply the common-field mutation contract: version +1, updated_at refreshed."""
    record["version"] += 1
    record["updated_at"] = CLOCK.now()


DB = Store()
