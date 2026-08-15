"""In-memory data store for the LTL Terminal Operations API.

The store starts completely empty on every process boot. No entity is ever
seeded, preloaded, or hardcoded at startup: every record is created through
the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Logical clock default at startup (PRD section 2.9).
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Collection name -> {id: record-dict}
store = {
    "terminals": {},
    "shipments": {},
    "pickup_routes": {},
    "pickup_stops": {},
    "dock_doors": {},
    "sortation_batches": {},
    "trailers": {},
    "manifest_entries": {},
    "linehaul_legs": {},
    "dimensioner_scans": {},
    "inspections": {},
    "osd_cases": {},
    "service_reports": {},
}

_seq = itertools.count(1)
_pro_serial = itertools.count(1)
_clock = {"now": _CLOCK_START}


def next_seq():
    """Global monotonic insertion counter (stable tiebreak for equal created_at)."""
    return next(_seq)


def next_pro_number():
    """PRO- followed by a zero-padded progressive serial."""
    return "PRO-{:06d}".format(next(_pro_serial))


def new_id():
    return str(uuid.uuid4())


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt
