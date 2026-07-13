"""In-memory data store and logical clock.

Everything lives in module-level dicts so a fresh process starts with an
empty store (the per-test-server harness restarts before every test).
NO seeding of any kind happens here or anywhere else.
"""

import uuid
import itertools
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Collections keyed by id
# ---------------------------------------------------------------------------
connections = {}
devices = {}
testers = {}
appointments = {}
reports = {}
surveys = {}
notices = {}
repair_orders = {}
reminders = {}

_seq_counter = itertools.count(1)

# ---------------------------------------------------------------------------
# Logical clock (domain temporal evaluation).  Startup default per PRD 2.5.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def current_utc():
    return _clock["now"]


def set_current_utc(dt):
    _clock["now"] = dt
    return dt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def wall_now():
    """Real wall-clock UTC used for created_at / updated_at metadata."""
    return datetime.now(timezone.utc)
