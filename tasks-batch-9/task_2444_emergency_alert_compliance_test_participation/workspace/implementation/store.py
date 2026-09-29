"""In-memory data store.

Every collection starts empty on every fresh process.  No entity is ever seeded,
preloaded or hardcoded: tests build all preconditions through the declared API.
"""

import itertools
import uuid

from flask import g

import clock

_seq_counter = itertools.count(1)


class Store:
    def __init__(self):
        self.state_plans = {}
        self.stations = {}
        self.relay_rules = {}
        self.devices = {}
        self.assignments = {}
        self.outages = {}
        self.alerts = {}
        self.wea_notices = {}
        self.test_events = {}
        self.log_entries = {}
        self.filings = {}
        self.inspections = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def base_row(versioned=True):
    """Common audit fields (PRD 2.5)."""
    row = {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": clock.now(),
    }
    if versioned:
        row["updated_at"] = clock.now()
        row["version"] = 1
    return row


def _touched():
    tset = getattr(g, "touched_rows", None)
    if tset is None:
        tset = set()
        g.touched_rows = tset
    return tset


def mark_created(row):
    """A row created inside this request must not have its version bumped again."""
    _touched().add(row["id"])


def touch(row):
    """Refresh updated_at and bump version — at most once per row per request."""
    if "version" not in row:
        return row
    tset = _touched()
    row["updated_at"] = clock.now()
    if row["id"] not in tset:
        tset.add(row["id"])
        row["version"] = row.get("version", 1) + 1
    return row


def order_key(row):
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=order_key)


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------

def assignments_of_station(station_id):
    return ordered([a for a in db.assignments.values() if a["station_id"] == station_id])


def assignments_of_device(device_id):
    return ordered([a for a in db.assignments.values() if a["device_id"] == device_id])


def devices_of_station(station_id):
    return ordered([d for d in db.devices.values() if d["station_id"] == station_id])


def test_events_of_station(station_id):
    return ordered([t for t in db.test_events.values() if t["station_id"] == station_id])


def alerts_of_station(station_id):
    return ordered([a for a in db.alerts.values() if a["station_id"] == station_id])


def log_entries_of_event(test_event_id):
    return ordered([e for e in db.log_entries.values() if e["test_event_id"] == test_event_id])


def filings_of_event(test_event_id):
    return ordered([f for f in db.filings.values() if f["test_event_id"] == test_event_id])


def filings_of_station(station_id):
    out = []
    for f in db.filings.values():
        ev = db.test_events.get(f["test_event_id"])
        if ev is not None and ev["station_id"] == station_id:
            out.append(f)
    return ordered(out)


def outages_of_station(station_id):
    out = []
    for o in db.outages.values():
        dev = db.devices.get(o["device_id"])
        if dev is not None and dev["station_id"] == station_id:
            out.append(o)
    return ordered(out)


def outages_of_device(device_id):
    return ordered([o for o in db.outages.values() if o["device_id"] == device_id])


def inspections_of_station(station_id):
    return ordered([i for i in db.inspections.values() if i["station_id"] == station_id])


def relay_rules_of_plan(state_plan_id):
    return ordered([r for r in db.relay_rules.values() if r["state_plan_id"] == state_plan_id])


def stations_of_plan(state_plan_id):
    return ordered([s for s in db.stations.values() if s["state_plan_id"] == state_plan_id])


def wea_notices_of_station(station_id):
    return ordered([w for w in db.wea_notices.values() if w["station_id"] == station_id])
