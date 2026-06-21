"""In-memory data store.

All state lives in module-level dicts keyed by entity id. There is NO disk
persistence and NO seeding: a fresh process starts completely empty, which is
what the per-test-server isolation requires (start.sh re-launch wipes state).
"""

import uuid
from datetime import datetime, timezone

# Entity tables --------------------------------------------------------------
studios = {}
rooms = {}
instructors = {}
class_templates = {}
package_plans = {}
members = {}
memberships = {}
wallet_entries = {}
class_sessions = {}
reservations = {}
fee_charges = {}

# Logical clock --------------------------------------------------------------
# Server "current UTC clock". Driven by POST /_clock/set_current_utc. Until set,
# it tracks wall-clock UTC so time-dependent rules still have a value.
_clock = {"now": None}


def now_clock():
    """Return the current logical clock as a timezone-aware UTC datetime."""
    if _clock["now"] is not None:
        return _clock["now"]
    return datetime.now(timezone.utc)


def set_clock(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def utcnow():
    """Wall-clock UTC; used for created_at/updated_at stamping of records."""
    return datetime.now(timezone.utc)
