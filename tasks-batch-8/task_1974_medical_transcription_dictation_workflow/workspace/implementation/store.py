"""In-memory data store and the vendor-operated logical clock.

Storage is in-memory only: plain dicts keyed by id. The store starts empty on
every boot; nothing is seeded. All server-stamped timestamps read the logical
clock, which starts at the fixed default 2026-08-01T00:00:00Z and never falls
back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

db = {
    "clinics": {},
    "sla_policies": {},
    "providers": {},
    "editors": {},
    "shift_windows": {},
    "jobs": {},
    "transcripts": {},
    "qa_reviews": {},
    "templates": {},
    "macros": {},
    "billing_periods": {},
    "line_items": {},
}

_clock = {"now": DEFAULT_CLOCK}
_seq = {"n": 0}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def next_seq():
    """Global monotonic creation counter — stable tie-break for created_at ASC ordering."""
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())
