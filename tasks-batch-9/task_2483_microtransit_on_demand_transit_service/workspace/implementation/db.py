"""In-memory data store.

The store starts completely empty on every boot: nothing is seeded, preloaded,
registered or hardcoded.  Every entity is created through the declared API.
"""
import uuid

import clock

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


class Store(dict):
    """Ordered id -> record map."""

    def add(self, rec):
        self[rec["id"]] = rec
        return rec

    def ordered(self):
        """Every record in created_at ASC order (insertion sequence breaks ties)."""
        return sorted(self.values(), key=sort_key)


service_zones = Store()
virtual_stops = Store()
transit_connections = Store()
vehicles = Store()
drivers = Store()
riders = Store()
demand_forecasts = Store()
vehicle_blocks = Store()
trip_requests = Store()
pool_assignments = Store()
fare_transactions = Store()
subsidy_reports = Store()

ALL_STORES = [
    service_zones, virtual_stops, transit_connections, vehicles, drivers,
    riders, demand_forecasts, vehicle_blocks, trip_requests, pool_assignments,
    fare_transactions, subsidy_reports,
]


def reset():
    for store in ALL_STORES:
        store.clear()
    _seq["n"] = 0
    clock.reset()


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def base_record(versioned=True):
    stamp = clock.iso_now_ms()
    rec = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def _touched_set():
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        if not hasattr(g, "_touched_rows"):
            g._touched_rows = set()
        return g._touched_rows
    except Exception:  # pragma: no cover - defensive
        return None


def touch(rec):
    """Advance a mutated row exactly once per request (PRD Section 2.10).

    "Any row a request writes to -- the primary target or a cascade victim --
    gets a fresh updated_at and a version one higher than before."  A row
    written to several times inside one request therefore still advances by
    exactly one.
    """
    if rec is None or "version" not in rec:
        return rec
    touched = _touched_set()
    if touched is not None:
        if rec["id"] in touched:
            return rec
        touched.add(rec["id"])
    rec["version"] += 1
    rec["updated_at"] = clock.iso_now_ms()
    return rec


def by_created_at(records):
    return sorted(records, key=sort_key)
