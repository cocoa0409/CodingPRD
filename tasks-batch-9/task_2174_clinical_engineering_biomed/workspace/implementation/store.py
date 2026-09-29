"""In-memory data store and the logical clock.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded; every row is created by a client through the declared API surface.
"""
from __future__ import annotations

import datetime as _dt
import threading

import util
from errors import ApiError, NOT_FOUND_FOR

CLOCK_DEFAULT = _dt.datetime(2026, 8, 1, 0, 0, 0)

COLLECTIONS = (
    "Facility",
    "Department",
    "Vendor",
    "DeviceModel",
    "Device",
    "PMTask",
    "WorkOrder",
    "LoanerAssignment",
    "RecallNotice",
    "RecallMatch",
    "ServiceContract",
    "SecurityFinding",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = {name: {} for name in COLLECTIONS}
        self.clock = CLOCK_DEFAULT
        self.clock_raw = util.format_dt(CLOCK_DEFAULT)
        self._seq = 0

    # ---------------- clock ----------------
    def now(self) -> _dt.datetime:
        return self.clock

    def now_iso(self) -> str:
        return util.format_dt(self.clock)

    def set_clock(self, dt: _dt.datetime, raw: str):
        self.clock = dt
        self.clock_raw = raw

    # ---------------- identity ----------------
    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ---------------- crud ----------------
    def insert(self, kind: str, record: dict) -> dict:
        self.data[kind][record["id"]] = record
        return record

    def get(self, kind: str, rid):
        if not isinstance(rid, str):
            return None
        return self.data[kind].get(rid)

    def require(self, kind: str, rid) -> dict:
        rec = self.get(kind, rid)
        if rec is None:
            raise ApiError(NOT_FOUND_FOR[kind])
        return rec

    def all(self, kind: str):
        return list(self.data[kind].values())

    def new_record(self, kind: str, fields: dict) -> dict:
        now = self.now_iso()
        rec = {
            "id": util.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        rec.update(fields)
        rec["_seq"] = self.next_seq()
        rec["_kind"] = kind
        return self.insert(kind, rec)

    def ordered(self, records):
        return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))

    def touch(self, rec: dict):
        """Refresh updated_at and bump version by exactly 1 (PRD 2.10)."""
        rec["updated_at"] = self.now_iso()
        rec["version"] = rec["version"] + 1


store = Store()


def serialize(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_key(rec: dict):
    return (rec["created_at"], rec["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)
