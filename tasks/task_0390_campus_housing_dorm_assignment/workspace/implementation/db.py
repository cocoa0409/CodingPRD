"""In-memory data store.

All state lives in module-level dicts keyed by id. There is NO persistence:
every fresh process starts completely empty. NOTHING is seeded here.
"""

import threading
import uuid
from datetime import datetime, timezone


# A single coarse lock to keep multi-step mutations atomic within a process.
LOCK = threading.RLock()

# One dict per entity collection, keyed by entity id.
buildings = {}
rooms = {}
students = {}
housing_cycles = {}
applications = {}
roommate_groups = {}
roommate_memberships = {}
assignments = {}
meal_plans = {}
waitlist_entries = {}
damage_charges = {}
incident_reports = {}
break_housing_requests = {}

# Monotonic insertion counter so we can break created_at ties deterministically
# (timestamps can collide at sub-millisecond resolution).
_seq = 0


def reset():
    """Wipe all collections. Used only for safety; not called at startup."""
    for coll in (
        buildings, rooms, students, housing_cycles, applications,
        roommate_groups, roommate_memberships, assignments, meal_plans,
        waitlist_entries, damage_charges, incident_reports,
        break_housing_requests,
    ):
        coll.clear()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    global _seq
    _seq += 1
    return _seq
