"""In-memory data store, logical clock, and shared time/number helpers."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Named constants (authoritative values from SCAFFOLD global_constants)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

MIN_SHIFT_DURATION_HOURS = 4.0
MAX_SHIFT_DURATION_HOURS = 16.0
MIN_REST_HOURS_BETWEEN_SHIFTS = 8.0
MAX_WEEKLY_SCHEDULED_HOURS = 60.0
MAX_ORDER_HEADCOUNT = 20

SHIFT_CLAIM_LOCK_HOURS = 2.0
MAX_OPEN_CLAIMS_PER_CLINICIAN = 5

CREDENTIAL_BUFFER_DAYS = 1

UNPAID_BREAK_THRESHOLD_MINUTES = 360
UNPAID_BREAK_MINUTES = 30

NIGHT_WINDOW_START_HOUR = 19
NIGHT_WINDOW_END_HOUR = 7
NIGHT_DIFF_CENTS_PER_HOUR = 450
WEEKEND_DIFF_CENTS_PER_HOUR = 300
CRISIS_RATE_MULTIPLIER = Decimal("1.25")
OVERTIME_THRESHOLD_HOURS = Decimal("40.0")
OVERTIME_MULTIPLIER = Decimal("1.5")

TIMESHEET_SUBMISSION_WINDOW_DAYS = 7
TIMESHEET_MAX_DISPUTE_ROUNDS = 2

CANCELLATION_FREE_HOURS = Decimal("72.0")
CANCELLATION_LATE_HOURS = Decimal("24.0")
CANCEL_PENALTY_POINTS_LATE = 5
CANCEL_PENALTY_POINTS_VERY_LATE = 15
NO_SHOW_PENALTY_POINTS = 30
SHIFT_COMPLETION_CREDIT_POINTS = 2
FACILITY_CANCELLATION_CREDIT_POINTS = 2
RELIABILITY_BASE_SCORE = 100
RELIABILITY_MIN_SCORE = 0
RELIABILITY_MAX_SCORE = 100
RELIABILITY_WINDOW_DAYS = 90
RELIABILITY_WEIGHT_TIER1_MAX_AGE_DAYS = 30
RELIABILITY_WEIGHT_TIER1 = Decimal("1.0")
RELIABILITY_WEIGHT_TIER2_MAX_AGE_DAYS = 60
RELIABILITY_WEIGHT_TIER2 = Decimal("0.6")
RELIABILITY_WEIGHT_TIER3_MAX_AGE_DAYS = 90
RELIABILITY_WEIGHT_TIER3 = Decimal("0.3")
RELIABILITY_SUSPENSION_THRESHOLD = 60

MARKUP_TIER1_MAX_CENTS = 200000
MARKUP_TIER2_MAX_CENTS = 500000
MARKUP_TIER1_MULTIPLIER = Decimal("1.45")
MARKUP_TIER2_MULTIPLIER = Decimal("1.38")
MARKUP_TIER3_MULTIPLIER = Decimal("1.32")
INVOICE_NET_TERMS_DAYS = 30
INVOICE_MAX_PERIOD_DAYS = 31

CREDENTIAL_TYPES = {"RN_LICENSE", "BLS", "ACLS", "TB_SCREENING", "FIT_TEST"}
SPECIALTIES = {"RN", "LPN", "CNA", "RT", "PT"}
ROLES = {"PlatformAdmin", "ComplianceOfficer", "FacilityScheduler",
         "FacilityVerifier", "Clinician", "BillingAgent"}


class DB:
    """Fresh in-memory store. Rebuilt on every process boot; never seeded."""

    def __init__(self):
        self.facilities = {}
        self.clinicians = {}
        self.credentials = {}
        self.rate_cards = {}
        self.orders = {}
        self.shifts = {}
        self.claims = {}
        self.assignments = {}
        self.timesheets = {}
        self.reliability_events = {}
        self.invoices = {}
        self.clock = parse_iso(DEFAULT_CLOCK_UTC)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


def now():
    return db.clock


def new_id():
    return str(uuid4())


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO 8601 string to an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def render_dt(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def is_iso_datetime(s):
    try:
        parse_iso(s)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def rhu(value, places):
    """round_half_up to a given number of decimal places, returns Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(q, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """round_half_up to whole cents (integer)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_2dp(value):
    """round_half_up to 2 decimals as Decimal."""
    return rhu(value, 2)


# Instantiate the fresh in-memory store after all helpers are defined
# (DB.__init__ calls parse_iso for the default clock).
db = DB()
