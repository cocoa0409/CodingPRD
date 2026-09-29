"""Shared primitives: logical clock, id minting, rounding and domain constants.

Every timestamp in this service comes from the deterministic logical clock
(PRD 2.4); the host wall clock is never read.
"""
import calendar
import re
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---------------------------------------------------------------- roles
ROLES = (
    "CertificationOfficer",
    "Auditor",
    "CommitteeChair",
    "CommitteeMember",
    "ProducerRepresentative",
    "BrandLicensee",
)

# ---------------------------------------------------------------- enums
HOLDER_TYPES = ("PRODUCER_ORG", "PROCESSOR", "EXPORTER", "IMPORTER", "BRAND")
PRODUCT_CODES = ("COFFEE_ARABICA", "COCOA", "BANANA")
CERT_STATUSES = ("PENDING", "CERTIFIED", "SUSPENDED", "TRANSITIONING", "DECERTIFIED")
SUSPENSION_REASONS = ("NONE", "NONCONFORMITY_ESCALATION", "VOLUME_VARIANCE", "MANUAL")
SUSPEND_INPUT_REASONS = ("NONCONFORMITY_ESCALATION", "VOLUME_VARIANCE", "MANUAL")
LICENSE_STATUSES = ("NONE", "ACTIVE", "SUSPENDED", "TERMINATED")
LICENSE_TIERS = ("TIER_1", "TIER_2", "TIER_3")
NODE_ROLES = (
    "FARM", "COOPERATIVE", "PROCESSOR", "EXPORTER", "IMPORTER", "MANUFACTURER",
    "BRAND_NODE",
)
TRACEABILITY_MODES = ("PHYSICAL", "MASS_BALANCE")
NODE_STATUSES = ("REGISTERED", "ACTIVE", "SUSPENDED", "RETIRED")
COMMITTEE_STATUSES = ("FORMING", "ACTIVE", "RESTRICTED", "DISSOLVED")
USE_CATEGORIES = (
    "EDUCATION", "HEALTHCARE", "INFRASTRUCTURE", "PRODUCTIVITY_TOOLS",
    "WORKING_CAPITAL", "CASH_DISTRIBUTION",
)
ENTRY_TYPES = ("ACCRUAL", "REVERSAL", "COMMITMENT", "RELEASE", "DISBURSEMENT")
QUALITY_GRADES = ("STANDARD", "SPECIALTY")
PREMIUM_BASES = ("PHYSICAL_TRACEABILITY", "MASS_BALANCE")
VERIFICATION_STATUSES = ("UNVERIFIED", "VERIFIED", "DISPUTED", "REJECTED")
SETTLEMENT_STATUSES = ("PENDING", "SETTLED", "REVERSED")
RECONCILIATION_STATUSES = ("SUBMITTED", "MATCHED", "VARIANCE_FLAGGED")
BASES = ("SELLER_BASIS", "BUYER_BASIS")
PROPOSAL_STATUSES = (
    "DRAFT", "UNDER_VOTE", "REVISION_REQUESTED", "APPROVED", "REJECTED",
    "DISBURSED", "CANCELLED",
)
BALLOTS = ("APPROVE", "REJECT", "ABSTAIN")
AUDIT_TYPES = ("INITIAL", "SURVEILLANCE", "FOLLOW_UP", "UNANNOUNCED")
AUDIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "REPORT_PENDING", "CLOSED", "CANCELLED")
GRADES = ("CRITICAL", "MAJOR", "MINOR", "OBSERVATION")
NC_STATUSES = ("OPEN", "CAP_SUBMITTED", "CAP_REJECTED", "CLOSED", "OVERDUE", "ESCALATED")
NC_OPEN_STATUSES = ("OPEN", "CAP_SUBMITTED", "CAP_REJECTED", "OVERDUE", "ESCALATED")
CLAIM_TYPES = ("FT_CERTIFIED_100", "FT_INGREDIENT_MASS_BALANCE")
MARK_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "WITHDRAWN")

# ---------------------------------------------------------------- constants
MIN_FOB_PRICE_CENTS_PER_KG = {"COFFEE_ARABICA": 320, "COCOA": 260, "BANANA": 45}
ORGANIC_DIFFERENTIAL_CENTS_PER_KG = 80
QUALITY_DIFFERENTIAL_CENTS_PER_KG = {"STANDARD": 0, "SPECIALTY": 40}

PREMIUM_RATE_CENTS_PER_KG = {"COFFEE_ARABICA": 80, "COCOA": 60, "BANANA": 15}
ORGANIC_PREMIUM_UPLIFT_PCT = Decimal("0.25")
MASS_BALANCE_LOT_SIZE_KG = Decimal("1000")
MASS_BALANCE_ATTRIBUTION_FACTOR = Decimal("0.9725")

LICENSE_TIER_1_CAP_KG = Decimal("100000")
LICENSE_TIER_2_CAP_KG = Decimal("500000")
LICENSE_TIER_1_RATE_CENTS_PER_KG = Decimal("1.20")
LICENSE_TIER_2_RATE_CENTS_PER_KG = Decimal("0.80")
LICENSE_TIER_3_RATE_CENTS_PER_KG = Decimal("0.45")
LICENSE_BASE_FEE_CENTS = 250000
LICENSE_ADMIN_SURCHARGE_PCT = Decimal("0.035")

APPROVAL_PCT = Decimal("66.67")
VARIANCE_TOLERANCE_PCT = Decimal("2.00")
MAX_VARIANCE_HARD_PCT = Decimal("10.00")

SCORE_WEIGHT_CRITICAL = 40
SCORE_WEIGHT_MAJOR = 15
SCORE_WEIGHT_MINOR = 5
SCORE_WEIGHT_OBSERVATION = 0
BASE_CAP_DAYS = {"CRITICAL": 7, "MAJOR": 30, "MINOR": 90, "OBSERVATION": 180}

MAX_CHAIN_DEPTH = 6
AUDITOR_TRAVEL_BUFFER_DAYS = 3
TRANSITION_WINDOW_DAYS = 90
COMMITTEE_ACTIVATION_THRESHOLD_CENTS = 1000000
LOW_BALANCE_THRESHOLD_CENTS = 200000
FUND_WINDOW_CAPACITY_PCT = Decimal("80")

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100

# ---------------------------------------------------------------- numbers
def dec(value):
    """Coerce to Decimal without ever going through binary float arithmetic."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up on the absolute value, then reapply the sign (PRD 2.6)."""
    value = dec(value)
    quant = Decimal(1).scaleb(-places)
    if value < 0:
        return -((-value).quantize(quant, rounding=ROUND_HALF_UP))
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """Whole cents, integer."""
    return int(rhu(value, 0))


def vol(value):
    """Kilograms, exactly 3 decimals."""
    return rhu(value, 3)


def pct(value):
    """Percentages, exactly 2 decimals."""
    return rhu(value, 2)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------- clock
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_state = {"clock": None, "seq": 0}


def parse_iso(text):
    if not isinstance(text, str):
        raise ValueError("not a string")
    raw = text.strip()
    if not raw:
        raise ValueError("empty")
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(moment):
    if moment is None:
        return None
    return "%s.%03dZ" % (moment.strftime("%Y-%m-%dT%H:%M:%S"), moment.microsecond // 1000)


def clock_now():
    if _state["clock"] is None:
        _state["clock"] = parse_iso(DEFAULT_CLOCK_UTC)
    return _state["clock"]


def set_clock(moment):
    _state["clock"] = moment


def now_iso():
    return iso(clock_now())


def clock_date():
    return clock_now().date()


def add_days(moment, days):
    return moment + timedelta(days=days)


def add_months(base_date, months):
    """Calendar month addition, clamping to the last day of the target month."""
    total = base_date.month - 1 + months
    year = base_date.year + total // 12
    month = total % 12 + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def parse_date_str(text):
    if not isinstance(text, str) or not _ISO_DATE_RE.match(text.strip()):
        raise ValueError("bad date")
    return date.fromisoformat(text.strip())


def as_datetime(day):
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


# ---------------------------------------------------------------- ids
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def request_id():
    return "req_" + uuid.uuid4().hex[:20].upper()
