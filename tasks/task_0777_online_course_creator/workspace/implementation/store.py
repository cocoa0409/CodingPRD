"""In-memory data store, logical clock, and shared helpers.

Everything is process-local and starts EMPTY on every boot. No seeding.
"""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK = {"now": DEFAULT_CLOCK}


def now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


# --------------------------------------------------------------------------
# Entity stores (insertion-ordered dicts keyed by id)
# --------------------------------------------------------------------------
creators = {}
students = {}
courses = {}
lessons = {}
price_plans = {}
coupons = {}
affiliates = {}
enrollments = {}
invoices = {}
payouts = {}
quiz_attempts = {}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_serial():
    return "cert_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=16))


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------
def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Base entity construction / mutation
# --------------------------------------------------------------------------
def base(with_version=True, with_updated=True):
    dt = now()
    d = {
        "id": new_id(),
        "_seq": next_seq(),
        "_created_dt": dt,
    }
    if with_updated:
        d["_updated_dt"] = dt
    if with_version:
        d["version"] = 1
    return d


def touch(entity):
    """Register a mutation: refresh updated_at and advance version."""
    entity["_updated_dt"] = now()
    if "version" in entity:
        entity["version"] = entity["version"] + 1


def bump_creator_version(creator):
    creator["version"] = creator["version"] + 1
    creator["_updated_dt"] = now()
