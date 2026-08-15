"""In-memory data store, logical clock, and time helpers.

The store starts completely empty on every boot — no seeding of any kind.
All system timestamps read the logical clock, never wall-clock time.
"""
import threading
import uuid
from datetime import date, datetime, time, timedelta, timezone

CTR_THRESHOLD_CENTS = 1000000
NEAR_THRESHOLD_LOW_CENTS = 900000
FEE_BPS = 50
MIN_FEE_CENTS = 150
MONEY_ORDER_MAX_CENTS = 100000
RECORD_BAND_LOW_CENTS = 300000
RECORD_BAND_HIGH_CENTS = 1000000
EFILE_DEADLINE_DAYS = 15
PAPER_DEADLINE_DAYS = 25
AMENDMENT_WINDOW_DAYS = 45
REVIEW_PERIOD_DAYS = 365
PHASE_II_MIN_QUALIFYING_DAYS = 5
PHASE_II_MIN_ACCOUNT_AGE_DAYS = 60
ELIGIBILITY_WINDOW_DAYS = 365
STRUCTURING_WINDOW_DAYS = 5
TRAILING_RECOMPUTE_DATES = 45

ROLES = (
    "SystemAdmin",
    "BranchManager",
    "Teller",
    "ComplianceAnalyst",
    "BSAOfficer",
    "Examiner",
)

CUSTOMER_TYPES = (
    "INDIVIDUAL",
    "BUSINESS_NONLISTED",
    "BUSINESS_LISTED",
    "BANK",
    "GOVERNMENT_AGENCY",
    "PAYROLL_CUSTOMER",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.branches = {}
        self.customers = {}
        self.cash_transactions = {}
        self.instrument_sales = {}
        self.aggregations = {}  # keyed by (customer_id, business_date)
        self.ctrs = {}
        self.exemptions = {}
        self.alerts = {}
        self.cases = {}
        self.findings = {}
        self.audit_events = []
        # Startup default before any clock call: exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # internal monotonic insertion sequence (never serialized)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


def today():
    return store.clock.date()


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(store.clock)


def parse_dt(value):
    """Parse an ISO 8601 datetime (or bare date) into an aware UTC datetime.

    Returns None when the value is not a parseable string.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_strict(value):
    """Parse a strict YYYY-MM-DD date string. Returns a date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def due_date_str(base_date, days):
    return (base_date + timedelta(days=days)).isoformat()


def due_instant_end(date_str):
    """23:59:59.999 UTC on the given YYYY-MM-DD date."""
    d = parse_date_strict(date_str)
    return datetime.combine(d, time(23, 59, 59, 999000), tzinfo=timezone.utc)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28 in non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def stamp_new(entity):
    """Assign common system fields on creation."""
    store.seq += 1
    entity["_seq"] = store.seq
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1


def touch(entity):
    """Refresh updated_at and increment version on any mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def public(entity):
    """Strip internal bookkeeping fields before serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
