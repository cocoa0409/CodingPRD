"""In-memory data store, logical clock and row bookkeeping.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every row is created by a client through a declared endpoint.
"""
import itertools
import uuid
from decimal import Decimal

from errors import ApiError
from util import format_iso, parse_iso

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00.000Z"

COLLECTIONS = (
    "markets",
    "quota_cells",
    "universe_estimates",
    "edit_rule_sets",
    "households",
    "meters",
    "tuning_intervals",
    "processing_runs",
    "household_weights",
    "clients",
    "client_deliverables",
    "client_notifications",
    "methodology_changes",
    "accreditation_audits",
)

NOT_FOUND = {
    "markets": "ERR_MARKET_NOT_FOUND",
    "quota_cells": "ERR_QUOTA_CELL_NOT_FOUND",
    "universe_estimates": "ERR_UNIVERSE_ESTIMATE_NOT_FOUND",
    "edit_rule_sets": "ERR_EDIT_RULE_SET_NOT_FOUND",
    "households": "ERR_HOUSEHOLD_NOT_FOUND",
    "meters": "ERR_METER_NOT_FOUND",
    "tuning_intervals": "ERR_TUNING_INTERVAL_NOT_FOUND",
    "processing_runs": "ERR_PROCESSING_RUN_NOT_FOUND",
    "household_weights": "ERR_HOUSEHOLD_WEIGHT_NOT_FOUND",
    "clients": "ERR_CLIENT_NOT_FOUND",
    "client_deliverables": "ERR_CLIENT_DELIVERABLE_NOT_FOUND",
    "client_notifications": "ERR_CLIENT_NOTIFICATION_NOT_FOUND",
    "methodology_changes": "ERR_METHODOLOGY_CHANGE_NOT_FOUND",
    "accreditation_audits": "ERR_ACCREDITATION_AUDIT_NOT_FOUND",
}


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.data = {}
        for name in COLLECTIONS:
            self.data[name] = {}
        self._seq = itertools.count(1)
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)
        self._dirty = []
        self._dirty_ids = set()

    # ------------------------------------------------------------ clock
    def now_iso(self):
        return format_iso(self.clock)

    def set_clock(self, dt):
        previous = self.clock
        self.clock = dt
        return previous

    # ------------------------------------------------------------ rows
    def collection(self, name):
        return self.data[name]

    def insert(self, name, fields):
        row = dict(fields)
        row["id"] = str(uuid.uuid4())
        row["created_at"] = self.now_iso()
        row["updated_at"] = self.now_iso()
        row["version"] = 1
        row["_seq"] = next(self._seq)
        row["_kind"] = name
        self.data[name][row["id"]] = row
        return row

    def delete(self, name, row):
        self.data[name].pop(row["id"], None)
        if row["id"] in self._dirty_ids:
            self._dirty_ids.discard(row["id"])
            self._dirty = [r for r in self._dirty if r["id"] != row["id"]]

    def touch(self, row):
        """Mark a row mutated: exactly one version bump per request."""
        if row is None:
            return row
        if row["id"] not in self._dirty_ids:
            self._dirty_ids.add(row["id"])
            self._dirty.append(row)
        return row

    def flush(self):
        """Apply the pending version/updated_at bumps for this request."""
        pending, self._dirty = self._dirty, []
        self._dirty_ids = set()
        stamp = self.now_iso()
        for row in pending:
            if row["id"] in self.data.get(row["_kind"], {}):
                row["version"] = row["version"] + 1
                row["updated_at"] = stamp
        return pending

    # ------------------------------------------------------------ lookups
    def get(self, name, row_id):
        if not isinstance(row_id, str) or not row_id:
            return None
        return self.data[name].get(row_id)

    def must_get(self, name, row_id, error_id=None):
        row = self.get(name, row_id)
        if row is None:
            raise ApiError(error_id or NOT_FOUND[name])
        return row

    def all(self, name):
        return list(self.data[name].values())

    def where(self, name, **filters):
        rows = []
        for row in self.data[name].values():
            ok = True
            for key, value in filters.items():
                if row.get(key) != value:
                    ok = False
                    break
            if ok:
                rows.append(row)
        return rows


db = Store()


def seq_key(row):
    return row["_seq"]


def created_key(row):
    return (row["created_at"], row["_seq"])


def public(row):
    """Strip internal bookkeeping keys and JSON-ify Decimal values."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = [float(v) if isinstance(v, Decimal) else v for v in value]
        else:
            out[key] = value
    return out
