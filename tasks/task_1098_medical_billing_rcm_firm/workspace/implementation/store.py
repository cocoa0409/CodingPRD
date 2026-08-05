"""In-memory data store, logical clock, id and timestamp helpers.

All state lives in module-level dicts keyed by id. A fresh process starts empty:
nothing is seeded here or in app.py — every entity is created via the API.
"""
from datetime import datetime, timedelta
from uuid import uuid4

# ---------------------------------------------------------------------------
# Collections (keyed by id)
# ---------------------------------------------------------------------------
practices = {}
payers = {}
providers = {}
payer_enrollments = {}
fee_schedules = {}
fee_schedule_lines = {}
claims = {}
claim_lines = {}
denials = {}
appeals = {}
remittances = {}
payment_postings = {}
patient_statements = {}

ALL_COLLECTIONS = [
    practices, payers, providers, payer_enrollments, fee_schedules,
    fee_schedule_lines, claims, claim_lines, denials, appeals,
    remittances, payment_postings, patient_statements,
]

# ---------------------------------------------------------------------------
# Logical clock (§2.10). Before any client sets it the clock reads
# 2026-05-01T00:00:00Z. Never the host wall-clock.
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0)
_clock = {"now": _DEFAULT_CLOCK}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def reset_clock():
    _clock["now"] = _DEFAULT_CLOCK


# ---------------------------------------------------------------------------
# Ids and timestamps
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid4())


def parse_dt(value):
    """Parse an ISO-8601 string into a naive UTC datetime. Returns None for None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def render_dt(dt):
    """Render a naive UTC datetime as ISO-8601 with exactly three fractional
    digits and a trailing Z. Used for EVERY timestamp the platform emits, both
    server-stamped and echoed input dates, so formats never diverge."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        dt = parse_dt(dt)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % millis) + "Z"


def day_diff(later, earlier):
    """Whole days from `earlier` to `later`, floor of elapsed seconds / 86400."""
    if later is None or earlier is None:
        return None
    delta = later - earlier
    return int(delta.total_seconds() // 86400)
