"""In-memory data store, logical clock, and shared helpers.

All state lives in module-level dicts that start empty on every process boot.
No seeding is performed at import time.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FPL_BASE_CENTS = 1508000
FPL_INCREMENT_CENTS = 536000
MAX_PRIORITY_POINTS = 90
OFFER_WINDOW_DAYS = 14
DEFAULT_ADA_CHRONIC_THRESHOLD = 0.10
CLOCK_DEFAULT_ISO = "2026-03-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Collections (id -> record dict)
# ---------------------------------------------------------------------------
programs = {}
cohorts = {}
families = {}
applications = {}
offers = {}
enrollments = {}
attendance_records = {}
health_screenings = {}
home_visits = {}
transition_plans = {}
pir_reports = {}

_seq_counter = 0

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_clock = {"now": None}


def _parse_iso(value):
    """Parse an ISO-8601 instant (accepts trailing Z) into an aware datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    if _clock["now"] is None:
        _clock["now"] = _parse_iso(CLOCK_DEFAULT_ISO)
    return _clock["now"]


def set_clock(iso_value):
    _clock["now"] = _parse_iso(iso_value)


def format_dt(dt):
    """ISO-8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return format_dt(clock_now())


def real_now_iso():
    return format_dt(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# ID / sequence helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def new_record(fields, with_version=True):
    ts = now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["_seq"] = next_seq()
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: bump version and refresh updated_at."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()


def offer_expiry(offered_at_dt):
    return offered_at_dt + timedelta(days=OFFER_WINDOW_DAYS)
