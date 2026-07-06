"""In-memory data store. Starts empty on every boot. No seeding."""
import uuid

from clock import clock


class Store:
    """A single table keyed by id. Preserves insertion order for created_at tie-breaking."""

    def __init__(self):
        self._by_id = {}  # id -> dict

    def insert(self, row):
        self._by_id[row["id"]] = row

    def get(self, _id):
        return self._by_id.get(_id)

    def all(self):
        return list(self._by_id.values())

    def delete(self, _id):
        return self._by_id.pop(_id, None)

    def __len__(self):
        return len(self._by_id)


# One store per entity. All empty on module load.
creators = Store()
storefronts = Store()
products = Store()
variants = Store()
designs = Store()
listings = Store()
orders = Store()
fulfillment_partners = Store()
fulfillment_jobs = Store()
reprint_requests = Store()
payout_cycles = Store()
channel_sync_events = Store()


def new_id():
    return str(uuid.uuid4())


def new_common_fields():
    """Fields shared by every mutable entity: id, created_at, updated_at, version, and
    an internal _seq for stable sort tie-breaking (PRD §2.3)."""
    now_iso = clock.now_iso()
    return {
        "id": new_id(),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": clock.next_seq(),
    }


def bump(row):
    """Refresh updated_at and increment version on every mutation."""
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 1) + 1


def sorted_rows(rows):
    """Sort by (created_at asc, _seq asc). PRD §2.3: never break ties by id."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def public(row, drop=("_seq",)):
    """Copy a row for output, dropping internal fields."""
    return {k: v for k, v in row.items() if k not in drop}
