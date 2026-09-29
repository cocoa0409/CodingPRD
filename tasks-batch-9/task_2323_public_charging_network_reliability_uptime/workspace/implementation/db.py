"""In-memory data store.

Every collection starts empty on every boot — nothing is seeded, preloaded or
hardcoded.  All state is created through the declared API surface.
"""
import uuid
from flask import g

import clock

host_sites = {}
stations = {}
ports = {}
outages = {}
dispatches = {}
spare_parts = {}
reservations = {}
reports = {}
claims = {}
complaints = {}

_seq = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def base_record():
    stamp = clock.now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(row):
    """Record a mutation of `row`: bump `version` by one and refresh
    `updated_at`.  A resource touched several times inside one request (the
    cascades routinely do) is bumped exactly once — PRD §2.6 / §3.3: every
    entity touched at every link has its own `version` incremented (by one)."""
    if row is None:
        return row
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    if row["id"] in seen:
        return row
    seen.add(row["id"])
    row["version"] += 1
    row["updated_at"] = clock.now()
    return row


def mark_fresh(row):
    """Creation counts as the first write; never bump it again this request."""
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    seen.add(row["id"])
    return row


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def ports_of_station(station_id):
    return sort_rows([p for p in ports.values() if p["station_id"] == station_id])


def outages_of_port(port_id):
    return sort_rows([o for o in outages.values() if o["port_id"] == port_id])


def outages_of_station(station_id):
    port_ids = {p["id"] for p in ports.values() if p["station_id"] == station_id}
    return sort_rows([o for o in outages.values() if o["port_id"] in port_ids])


def dispatches_of_outage(outage_id):
    return sort_rows([d for d in dispatches.values() if d["outage_event_id"] == outage_id])


def dispatches_of_port(port_id):
    return sort_rows([d for d in dispatches.values() if d["port_id"] == port_id])


def reservations_of_dispatch(dispatch_id):
    return sort_rows([r for r in reservations.values() if r["dispatch_id"] == dispatch_id])


def reservations_of_part(spare_part_id):
    return sort_rows([r for r in reservations.values() if r["spare_part_id"] == spare_part_id])


def reports_of_station(station_id):
    return sort_rows([r for r in reports.values() if r["station_id"] == station_id])


def claims_of_report(report_id):
    return sort_rows([c for c in claims.values() if c["uptime_report_id"] == report_id])


def complaints_of_station(station_id):
    return sort_rows([c for c in complaints.values() if c["station_id"] == station_id])
