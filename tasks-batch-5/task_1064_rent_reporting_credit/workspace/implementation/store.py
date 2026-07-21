"""In-memory data store, logical clock, and low-level helpers.

Storage is process-local dicts keyed by id. Nothing is seeded at import time;
every entity is created through the API surface. The store starts empty on
every boot.
"""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GRACE_DAYS = 5
DISPUTE_WINDOW_DAYS = 30
DISPUTE_INVESTIGATION_DAYS = 30
BACK_REPORT_PER_MONTH_CENTS = 200
BACK_REPORT_FEE_CAP_CENTS = 3000
BACK_REPORT_MAX_MONTHS = 24

KNOWN_ROLES = {"Tenant", "Landlord", "ComplianceAnalyst", "ComplianceOfficer", "PlatformAdmin"}
BUREAUS = ["EQUIFAX", "EXPERIAN", "TRANSUNION"]

CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory collections (one dict per entity type)
# ---------------------------------------------------------------------------
tenants = {}
landlords = {}
plans = {}
enrollments = {}
leases = {}
rent_payments = {}
reported_items = {}
disputes = {}
back_report_requests = {}
invoices = {}
score_snapshots = {}

_seq_counter = {"n": 0}
_clock = {"now": CLOCK_DEFAULT}


def reset():
    for d in (tenants, landlords, plans, enrollments, leases, rent_payments,
              reported_items, disputes, back_report_requests, invoices, score_snapshots):
        d.clear()
    _seq_counter["n"] = 0
    _clock["now"] = CLOCK_DEFAULT


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Id / sequence helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Datetime parse / format
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 datetime (or date) string to an aware UTC datetime.
    Raises ValueError on failure."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        # date-only form YYYY-MM-DD
        dt = datetime.fromisoformat(t + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Calendar-month arithmetic
# ---------------------------------------------------------------------------
def add_one_month(dt):
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    # clamp day to last valid day of the target month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


# ---------------------------------------------------------------------------
# Mutation helper: refresh updated_at + bump version where those fields exist
# ---------------------------------------------------------------------------
def touch(entity):
    if "version" in entity:
        entity["version"] = entity["version"] + 1
    if "updated_at" in entity:
        entity["updated_at"] = clock_now()
    return entity


def base_fields(with_version=True):
    now = clock_now()
    f = {"id": new_id(), "created_at": now, "_seq": next_seq()}
    if with_version:
        f["updated_at"] = now
        f["version"] = 1
    return f
