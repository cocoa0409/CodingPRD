"""In-memory data store, logical clock, id/seq generation, and datetime helpers.

Everything lives in module-level dicts that are re-created on every process
start, so a fresh `python3 app.py` always begins with an empty store and the
default logical clock.  NOTHING is seeded here.
"""

import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Domain constants (from SCAFFOLD calculations / PRD narrative)
# ---------------------------------------------------------------------------
ANSWER_WINDOW_DAYS = 14
INSTALLMENT_INTERVAL_DAYS = 30
INCOME_CAP_BASE_CENTS = 300000
INCOME_CAP_PER_MEMBER_CENTS = 100000
ASSISTANCE_PROGRAM_BUDGET_CENTS = 5000000
JUDGMENT_FILING_FEE_CENTS = 4500
LOCKOUT_BUFFER_HOURS = 48
SEALING_WAIT_DAYS = 90

# ---------------------------------------------------------------------------
# Data collections — keyed by id
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "courts", "landlords", "tenants", "officers", "cases", "answers",
    "referrals", "mediation_sessions", "payment_plans", "installments",
    "hearings", "judgments", "lockout_orders", "sealing_requests",
]

db = {name: {} for name in COLLECTIONS}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_state = {"clock": DEFAULT_CLOCK, "seq": 0}


def now():
    """Current logical-clock instant (aware, UTC)."""
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Datetime parse / render — ONE canonical serializer for every timestamp.
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise ValueError("not a datetime string")
        s = value.strip()
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_dt(dt):
    """Render an aware datetime as ISO-8601 UTC with exactly three fractional
    digits and a trailing Z — the single canonical timestamp form."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)
