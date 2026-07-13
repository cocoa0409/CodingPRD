"""In-memory data store, logical clock, and low-level helpers.

Storage is process-local Python dicts only. Every launch of the server starts
with an empty store and the logical clock reset to its default. No entity data
is seeded at startup.
"""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta

# --- Logical clock -----------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# --- Entity tables -----------------------------------------------------------
PLANS = {}
VAULT_ITEMS = {}
DEPUTIES = {}
BENEFICIARIES = {}
DIRECTIVES = {}
RELEASE_REQUESTS = {}
SUBSCRIPTIONS = {}
SHARES = {}
INTEGRATIONS = {}
REVIEW_REMINDERS = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# --- datetime helpers --------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_now_wall():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1
