"""In-memory store. Starts empty on every boot; nothing is ever seeded."""
from datetime import datetime

from flask import g

from errors import ApiError
from util import UTC, new_id, wall_now

COLLECTION_NAMES = (
    "carriers",
    "stations",
    "seasons",
    "aircraft",
    "schedule_versions",
    "flight_legs",
    "slot_holdings",
    "slot_utilization_records",
    "slot_transactions",
    "filing_submissions",
    "route_authorities",
    "notification_obligations",
)

NOT_FOUND_ERROR = {
    "carriers": "ERR_CARRIER_NOT_FOUND",
    "stations": "ERR_STATION_NOT_FOUND",
    "seasons": "ERR_SEASON_NOT_FOUND",
    "aircraft": "ERR_AIRCRAFT_NOT_FOUND",
    "schedule_versions": "ERR_SCHEDULE_VERSION_NOT_FOUND",
    "flight_legs": "ERR_FLIGHT_LEG_NOT_FOUND",
    "slot_holdings": "ERR_SLOT_HOLDING_NOT_FOUND",
    "slot_utilization_records": "ERR_SLOT_UTILIZATION_RECORD_NOT_FOUND",
    "slot_transactions": "ERR_SLOT_TRANSACTION_NOT_FOUND",
    "filing_submissions": "ERR_FILING_SUBMISSION_NOT_FOUND",
    "route_authorities": "ERR_ROUTE_AUTHORITY_NOT_FOUND",
    "notification_obligations": "ERR_NOTIFICATION_OBLIGATION_NOT_FOUND",
}

# The logical clock's documented default, used whenever it has never been set.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.data = {name: {} for name in COLLECTION_NAMES}
        self.current_utc = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def coll(self, name):
        return self.data[name]

    def values(self, name):
        """Rows of a collection in creation order."""
        return sorted(self.data[name].values(), key=lambda row: row["_seq"])

    def get(self, name, row_id):
        if not isinstance(row_id, str):
            return None
        return self.data[name].get(row_id)

    def require(self, name, row_id):
        row = self.get(name, row_id)
        if row is None:
            raise ApiError(NOT_FOUND_ERROR[name])
        return row

    def insert(self, name, row, versioned=True):
        row["id"] = new_id()
        row["_seq"] = self.next_seq()
        stamp = wall_now()
        row["created_at"] = stamp
        if versioned:
            row["updated_at"] = stamp
            row["version"] = 1
        self.data[name][row["id"]] = row
        return row


store = Store()


def now():
    """The logical clock: the only clock any business rule reads."""
    return store.current_utc


def mark(row):
    """Register a row as written by this request; version bumps once at flush."""
    if row is None:
        return row
    dirty = getattr(g, "dirty_rows", None)
    if dirty is None:
        dirty = {}
        g.dirty_rows = dirty
    dirty[id(row)] = row
    return row


def flush():
    """Apply exactly one version/updated_at bump per row written by this request."""
    dirty = getattr(g, "dirty_rows", None)
    if not dirty:
        g.dirty_rows = {}
        return
    stamp = wall_now()
    for row in dirty.values():
        if "version" in row:
            row["version"] = row["version"] + 1
        if "updated_at" in row:
            row["updated_at"] = stamp
    g.dirty_rows = {}


def set_field(row, field, value):
    """Assign only when the value actually differs; report whether it changed."""
    if row.get(field) != value:
        row[field] = value
        return True
    return False


def apply_changes(row, changes):
    """Assign a dict of fields, marking the row dirty when anything really changed."""
    changed = False
    for field, value in changes.items():
        if set_field(row, field, value):
            changed = True
    if changed:
        mark(row)
    return changed


def public(row):
    """Strip internal bookkeeping keys from a row before serialisation."""
    return {k: v for k, v in row.items() if not k.startswith("_")}
