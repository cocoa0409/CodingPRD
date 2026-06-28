"""In-memory data store. Plain dicts keyed by id.

The store starts empty on every boot. NOTHING is seeded, preloaded, or
hardcoded at startup. Every entity is created by tests through the declared
API surface. Re-invoking start.sh (per-test-server isolation) wipes all state
because the process restarts and these module-level dicts are re-initialized.
"""
import uuid
from datetime import datetime, timezone

import clock

# One dict per collection, keyed by id.
menu_items = {}
add_ons = {}
patients = {}
memberships = {}
standing_orders = {}
nurses = {}
lounges = {}
appointments = {}
intake_screenings = {}
consents = {}
supply_lots = {}
dispatch_routes = {}
adverse_events = {}

# Monotonic insertion counter so list ordering by created_at is stable even
# when two records share the same logical-clock timestamp.
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """created_at/updated_at are minted from the logical clock."""
    return clock.now()


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(record):
    """Set common system fields on a freshly created record."""
    ts = now_ts()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version on a mutation."""
    record["updated_at"] = now_ts()
    record["version"] = record.get("version", 1) + 1
