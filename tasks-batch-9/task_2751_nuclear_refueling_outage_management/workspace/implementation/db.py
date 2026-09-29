"""In-memory data store.

Every collection starts EMPTY on every boot. Nothing is ever seeded, preloaded
or hardcoded here — the tests build all state through the declared endpoints.
"""
import uuid

from clock import clock


class Store(object):
    def __init__(self):
        self.outages = {}
        self.spent_fuel_pools = {}
        self.rad_areas = {}
        self.safety_functions = {}
        self.work_orders = {}
        self.schedule_activities = {}
        self.core_load_patterns = {}
        self.pool_cell_reservations = {}
        self.supplemental_workers = {}
        self.rwps = {}
        self.dose_transactions = {}
        self.emergent_items = {}
        self.startup_tests = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def create_row(collection, fields, common=True):
    """Insert a new row. `fields` is an ordered dict of business fields."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = clock.now_iso()
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = store.next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4 / 2.9)."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = clock.now_iso()
    return row


def order_key(row):
    """Canonical ascending-created_at ordering.

    Identifiers never participate in ordering (PRD 2.9). The logical clock can
    hold still across several writes, so insertion sequence is the deterministic
    tie-break within one identical created_at value.
    """
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def all_rows(collection):
    return sorted_rows(list(collection.values()))
