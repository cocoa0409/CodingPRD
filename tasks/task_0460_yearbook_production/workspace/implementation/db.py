"""In-memory data store. Starts empty on every boot — NO seeding.

Each entity is a plain dict. Common system fields (id, created_at, updated_at,
version) are managed centrally. A monotonic insertion sequence `_seq` is kept on
every record purely as a stable tie-breaker for created_at-ascending sorts,
because the logical clock can stamp identical created_at values on many records.
"""
import uuid

from clock import now_iso_millis


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.yearbooks = {}
        self.ladder_pages = {}
        self.submissions = {}
        self.staff_assignments = {}
        self.ad_contracts = {}
        self.proofs = {}
        self.presale_orders = {}
        self.print_runs = {}
        self.distribution_records = {}
        self._seq_counter = 0

    def next_seq(self):
        self._seq_counter += 1
        return self._seq_counter


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Populate id + common system fields on a freshly created record."""
    ts = now_iso_millis()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Register a mutation: refresh updated_at, bump version.

    Every recompute of a derived field and every cascade transition counts as a
    mutation per PRD §2.5.
    """
    record["updated_at"] = now_iso_millis()
    record["version"] = record.get("version", 1) + 1


def sorted_by_created(records):
    """created_at ascending, stable via insertion sequence."""
    return sorted(records, key=lambda r: r["_seq"])
