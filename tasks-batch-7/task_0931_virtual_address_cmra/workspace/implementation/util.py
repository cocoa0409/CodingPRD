"""Constants, the logical clock, id minting, timestamp rendering and money maths."""

import datetime as _dt
import random
import re
import string
import threading
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# ---------------------------------------------------------------- constants
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
USPS_ROSTER_CAP = 12
FORM_1583_VALIDITY_DAYS = 1825
ID_DOC_EXPIRY_GRACE_DAYS = 0
SCAN_JOB_MAX_PAGES = 25
SCAN_REQUEST_MAX_PAGES = 200
MAX_SCAN_RETRIES = 2
NOTIFICATION_SLA_HOURS = 24
SOP_NOTIFICATION_SLA_HOURS = 4
CONSOLIDATION_MIN_ITEMS = 3
CONSOLIDATION_DISCOUNT_PCT = Decimal("0.15")
FORWARD_BRACKET_1_MAX_LB = Decimal("1.0")
FORWARD_BRACKET_1_CENTS = 850
FORWARD_BRACKET_2_MAX_LB = Decimal("5.0")
FORWARD_BRACKET_2_CENTS = 1750
FORWARD_BRACKET_3_MAX_LB = Decimal("20.0")
FORWARD_BRACKET_3_CENTS = 3900
FORWARD_BRACKET_4_CENTS = 7200
SERVICE_MULTIPLIER = {
    "ECONOMY": Decimal("1.00"),
    "PRIORITY": Decimal("1.45"),
    "EXPRESS": Decimal("2.20"),
}
CHECK_MAX_AMOUNT_CENTS = 500000
BATCH_MAX_TOTAL_CENTS = 2500000
BATCH_MAX_CHECKS = 25
BATCH_CUTOFF_HOUR_UTC = 21
NOTICE_PERIOD_DAYS = 30
FINAL_FORWARD_WINDOW_DAYS = 15
ABANDONMENT_RTS_DAYS = 10
RETENTION_FLOOR_DAYS = 30
RA_DEFAULT_RETENTION_DAYS = 1095
BILLING_CYCLE_LENGTH_DAYS = 30
PRORATION_DAYS_PER_CYCLE = 30
LOYALTY_TIER_1_MIN_CENTS = 15000
LOYALTY_TIER_1_PCT = Decimal("0.05")
LOYALTY_TIER_2_MIN_CENTS = 40000
LOYALTY_TIER_2_PCT = Decimal("0.10")
SCAN_TIER_MULTIPLIER = {"COVER": 1, "INTERIOR": 1, "OCR": 2}
DISPOSITION_RANK = {"DEPOSIT": 1, "FORWARD": 2, "RETURN": 3, "SHRED": 4}

ROLES = ("PlatformAdmin", "CmraOperator", "ComplianceOfficer", "Notary", "BoxHolder", "Recipient")

# ---------------------------------------------------------------- enums
ENUMS = {
    "tier_code": ["BASIC", "PLUS", "BUSINESS", "ENTERPRISE"],
    "carrier_code": ["USPS", "UPS", "FEDEX", "DHL", "AMAZON"],
    "recipient_kind": ["INDIVIDUAL", "BUSINESS", "MINOR"],
    "rejection_reason": ["ADDRESS_MISMATCH", "ILLEGIBLE", "NAME_MISMATCH", "INCOMPLETE_ID"],
    "doc_class": ["PHOTO", "ADDRESS"],
    "doc_type": ["DRIVERS_LICENSE", "PASSPORT", "STATE_ID", "UTILITY_BILL", "LEASE",
                 "VOTER_CARD", "VEHICLE_REGISTRATION"],
    "item_class": ["LETTER", "FLAT", "PACKAGE", "SOP"],
    "refusal_reason": ["NOT_ON_ROSTER", "OVERSIZE", "CARRIER_NOT_ACCEPTED", "HOLDER_REQUEST"],
    "scan_tier": ["COVER", "INTERIOR", "OCR"],
    "disposition_type": ["FORWARD", "SHRED", "DEPOSIT", "RETURN"],
    "service_level": ["ECONOMY", "PRIORITY", "EXPRESS"],
    "reason": ["ID_EXPIRY", "USPS_AUDIT", "ROSTER_ANOMALY", "PAYMENT"],
    "resolution": ["CLEARED", "ESCALATED_CLOSURE"],
    # query filters
    "handling_status": ["RECEIVED", "AWAITING_CLEARANCE", "HELD", "PENDING_DISPOSITION",
                        "FORWARDED", "SHREDDED", "DEPOSITED", "RETURNED", "REFUSED"],
    "storage_status": ["FREE_WINDOW", "ACCRUING", "RELEASED", "DESTROYED"],
    "roster_status": ["PENDING", "AUTHORIZED", "SUSPENDED", "REMOVED"],
    "release_eligibility": ["BLOCKED", "RELEASABLE"],
    "unit_type": ["SCAN_PAGE", "FORWARD", "STORAGE_DAY", "RECIPIENT"],
    "tranche": ["IN_TIER", "OVERAGE"],
    "service_status": ["PENDING_SETUP", "ACTIVE", "SUSPENDED", "CLOSING", "CLOSED"],
}

# `status` is an enum-valued query filter whose member set depends on the collection.
STATUS_ENUMS = {
    "form1583": ["DRAFT", "NOTARIZED", "ACCEPTED", "REJECTED", "EXPIRED"],
    "id_document": ["PENDING_REVIEW", "VERIFIED", "EXPIRED", "SUPERSEDED"],
    "scan_job": ["QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "ABANDONED"],
    "disposition": ["PENDING", "EXECUTED", "CANCELLED", "SUPERSEDED"],
    "forward_shipment": ["PRICED", "SHIPPED", "CANCELLED"],
    "deposit_batch": ["OPEN", "CLOSED"],
    "check_deposit": ["RECEIVED", "MATCHED", "DEPOSITED", "HELD", "RETURNED"],
    "compliance_review": ["OPEN", "SUSPENDED", "RESOLVED"],
    "billing_cycle": ["OPEN", "CLOSING", "CLOSED"],
    "cancellation": ["REQUESTED", "FINAL_FORWARD", "FINALIZED", "WITHDRAWN"],
}


# ---------------------------------------------------------------- logical clock
class LogicalClock:
    """Nothing in this system consults wall-clock time (PRD 2.5)."""

    def __init__(self):
        self.now = parse_instant(DEFAULT_CLOCK_UTC)

    def reset(self):
        self.now = parse_instant(DEFAULT_CLOCK_UTC)

    def date(self):
        return self.now.date()

    def hour(self):
        return self.now.hour


def parse_instant(text):
    """Accept 'Z', explicit offsets and any fractional precision."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


CLOCK = LogicalClock()


# --------------------------------------------------------------------------
# THE SINGLE PRODUCER of every rendered instant in this service (PRD 2.4:
# "exactly three fractional digits and a trailing Z", used unconditionally and
# independently of the format the clock was set with).  Nothing else in this
# codebase formats a datetime.
# --------------------------------------------------------------------------
def render_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(_dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000)


def render_date(d):
    """Server-computed calendar dates are plain YYYY-MM-DD strings."""
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_date(text):
    if not isinstance(text, str):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()):
        return None
    try:
        return _dt.date.fromisoformat(text.strip())
    except ValueError:
        return None


def add_days(d, n):
    return d + _dt.timedelta(days=n)


def add_hours(dt, n):
    return dt + _dt.timedelta(hours=n)


def whole_days_between(start_dt, end_dt):
    """Complete 86,400-second intervals, remainder discarded."""
    secs = (end_dt - start_dt).total_seconds()
    if secs <= 0:
        return 0
    return int(secs // 86400)


# ---------------------------------------------------------------- id minting
class _IdFactory:
    """
    UUID-shaped but MONOTONIC ids: a per-process counter occupies the high bits
    so ascending `id` is ascending creation order.  The list ordering rule
    tie-breaks on `id` at equal `created_at`, and the coarse logical clock puts
    many rows at one `created_at`; random UUIDs would make that ordering
    nondeterministic.  This is NOT seeded data -- the counter starts at zero on
    every boot and mints ids only for rows the API is asked to create.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._n = 0
        self._rand = random.Random(0xC17A)

    def reset(self):
        with self._lock:
            self._n = 0
            self._rand = random.Random(0xC17A)

    def next(self):
        with self._lock:
            self._n += 1
            n = self._n
            tail = self._rand.getrandbits(48)
        # 8-4-4-4-12; the first 12 hex digits are the zero-padded counter, so
        # lexicographic order == creation order.  Version nibble 4, variant 8.
        return "%08x-%04x-4%03x-8%03x-%012x" % (
            (n >> 16) & 0xFFFFFFFF, n & 0xFFFF, 0, 0, tail)


IDS = _IdFactory()


def new_id():
    return IDS.next()


ALNUM = string.ascii_uppercase + string.digits
_REQ_RANDOM = random.Random()


def new_request_id():
    return "req_" + "".join(_REQ_RANDOM.choice(ALNUM) for _ in range(20))


# ---------------------------------------------------------------- money
def round_half_up(value):
    """A value ending in exactly one half cent rounds away from zero (PRD 2.6)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))


def dec(value):
    return Decimal(str(value))


def num_out(value):
    """Render a 1-decimal-place measurement without binary-float noise."""
    if value is None:
        return None
    d = Decimal(str(value))
    q = d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if q == q.to_integral_value():
        return int(q)
    return float(q)


# ---------------------------------------------------------------- text
_SPACE_RUN = re.compile(r" +")


def normalize_name(text):
    """
    PAYEE_NORMALIZATION, used identically by roster matching and payee matching:
    uppercase, strip leading/trailing spaces, collapse internal runs of spaces to
    one, then delete the four characters . , ' and - (PRD 3.4, applied in the
    order the sentence states them).
    """
    if text is None:
        return ""
    s = str(text).upper().strip()
    s = _SPACE_RUN.sub(" ", s)
    for ch in (".", ",", "'", "-"):
        s = s.replace(ch, "")
    return s
