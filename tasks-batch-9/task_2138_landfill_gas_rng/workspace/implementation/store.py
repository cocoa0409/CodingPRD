"""In-memory data store and the logical clock.

Every collection starts EMPTY on boot. Nothing is seeded, preloaded or
hardcoded here; all state is created by API calls.
"""

import threading
from datetime import datetime

from common import UTC, new_uuid

LOCK = threading.RLock()

# The logical clock. Before POST /_clock/set_current_utc is ever called it
# reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {
    "current_utc": CLOCK_EPOCH,
    "seq": 0,
}

# --- collections (all keyed by id) -----------------------------------------
sites = {}
wells = {}
readings = {}
work_orders = {}
condensate_hauls = {}
plants = {}
downtime_events = {}
contracts = {}
nominations = {}
injection_batches = {}
attribute_batches = {}
compliance_reports = {}
royalty_statements = {}


def now():
    return _state["current_utc"]


def set_clock(when):
    _state["current_utc"] = when
    return when


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_row(**fields):
    """Create a row carrying id/created_at/updated_at/version."""
    row = {
        "id": new_uuid(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    row.update(fields)
    return row


def new_event_row(**fields):
    """Create an append-only event row: id + created_at only."""
    row = {
        "id": new_uuid(),
        "created_at": now(),
        "_seq": next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Advance updated_at and increment version on a mutated row."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Default listing order: created_at ascending, insertion order tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
