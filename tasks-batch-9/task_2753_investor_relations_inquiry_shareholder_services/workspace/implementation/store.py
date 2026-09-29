"""In-memory data store, logical clock (PRD §2.4) and common resource properties (§2.5).

Everything lives in plain Python dicts keyed by id.  Nothing is persisted; the
store is empty on every boot and NO entity is ever seeded here.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

# ---------------------------------------------------------------- logical clock
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.companies = {}
        self.contacts = {}
        self.disclosures = {}
        self.inquiries = {}
        self.drafts = {}
        self.estimates = {}
        self.events = {}
        self.meeting_requests = {}
        self.instructions = {}
        self.clock = LOGICAL_CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


store = Store()


# ------------------------------------------------------------------- primitives
def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD §2.9)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_date(dt):
    """A calendar date as ``YYYY-MM-DD`` (PRD §3.9: record_date and payable_date are
    dates compared at UTC calendar-date granularity, not timestamps)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def rhu(value, places):
    """round half up to `places` decimals; returns Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def floor4(value):
    """truncate toward zero to 4 decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return (value * 10000).to_integral_value(rounding=ROUND_DOWN) / Decimal(10000)


def numout(value):
    """Serialise a Decimal (or None) as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def new_row(extra=None):
    """Create a row carrying the four universal system fields (PRD §2.5)."""
    now = store.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """A mutation: refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = store.now()
    row["version"] = row["version"] + 1
    return row


def sorted_rows(table, rows=None):
    """Creation-order listing: created_at ascending, insertion sequence as the
    stable tiebreaker (identifiers are never used for ordering)."""
    if rows is None:
        rows = list(table.values())
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def common_out(row):
    return {
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


# ---------------------------------------------------------------- domain enums
ROLES = ["IRAdmin", "IRAnalyst", "DisclosureOfficer", "TransferAgentLiaison", "Investor"]

CONTACT_TYPES = ["INSTITUTIONAL_HOLDER", "RETAIL_HOLDER", "SELL_SIDE_ANALYST"]
HOLDER_TYPES = ("INSTITUTIONAL_HOLDER", "RETAIL_HOLDER")
COVERAGE_STATUSES = ["NOT_COVERING", "INITIATED", "SUSPENDED"]
THREAT_LEVELS = ["NONE", "WATCH", "ELEVATED", "CRITICAL"]
TARGET_TIERS = ["TIER_1", "TIER_2", "TIER_3", "UNTIERED"]
MODEL_ACCESS_STATUSES = ["NONE", "GRANTED", "REVOKED"]

DISCLOSURE_TYPES = ["EARNINGS_RELEASE", "GUIDANCE_UPDATE", "PRESS_RELEASE", "FORM_8K"]
METRICS = ["REVENUE", "EPS", "FCF_MARGIN"]
METRICS_WITH_NONE = ["REVENUE", "EPS", "FCF_MARGIN", "NONE"]
DISCLOSURE_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED", "WITHDRAWN"]

TOPIC_CATEGORIES = ["DIVIDEND", "RECORD_DATE", "PROXY", "GUIDANCE", "MODEL_REQUEST", "OTHER"]
ROUTING_QUEUES = ["SHAREHOLDER_SERVICES", "IR_DESK", "DISCLOSURE_COMMITTEE", "TRANSFER_AGENT_DESK"]
INQUIRY_STATUSES = ["NEW", "ROUTED", "DRAFTING", "AWAITING_APPROVAL", "ANSWERED", "ESCALATED"]
OPEN_INQUIRY_STATUSES = ("NEW", "ROUTED", "DRAFTING", "AWAITING_APPROVAL", "ESCALATED")

DISCLOSURE_CLASSES = ["PUBLIC_DOMAIN", "GUIDANCE_REPEAT", "MATERIAL_NONPUBLIC"]
DRAFT_STATUSES = ["DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "BLOCKED", "SENT"]
ACTIVE_DRAFT_STATUSES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED")

ESTIMATE_STATUSES = ["ACCEPTED", "SUPERSEDED"]

EVENT_TYPES = ["CONFERENCE", "NDR"]
EVENT_STATUSES = ["PLANNING", "OPEN_FOR_REQUESTS", "LOCKED", "COMPLETED"]
MEETING_STATUSES = ["REQUESTED", "ALLOCATED", "WAITLISTED", "RELEASED", "DECLINED"]
SLOT_MINUTES_ALLOWED = (20, 30, 45, 60)

INSTRUCTION_TYPES = ["RECORD_DATE_SET", "DIVIDEND_PAYMENT", "RECORD_INQUIRY"]
FUNDING_MODES = ["DECLARED_RATE", "RESERVE_CAPPED"]
INSTRUCTION_STATUSES = ["SUBMITTED", "ACKNOWLEDGED", "REJECTED", "EXECUTED", "REVERSED"]

# ------------------------------------------------------------------- constants
SLA_HOURS = {
    "DISCLOSURE_COMMITTEE": 48,
    "IR_DESK": 72,
    "TRANSFER_AGENT_DESK": 96,
    "SHAREHOLDER_SERVICES": 120,
}

TIER_1_MIN_PCT = Decimal("5.0")
TIER_2_MIN_PCT = Decimal("1.0")
ACTIVIST_STAKE_THRESHOLD_PCT = Decimal("5.0")

SENSITIVITY_BASE = {
    "GUIDANCE": 40,
    "MODEL_REQUEST": 30,
    "PROXY": 20,
    "DIVIDEND": 15,
    "RECORD_DATE": 15,
    "OTHER": 10,
}
SENSITIVITY_CAP = 100
NONPUBLIC_TERM = 25
ANALYST_TERM = 15
ACTIVIST_TERM = 10
ESCALATED_FOLLOWUP_TERM = 10
POSTURE_BLACKOUT_TERM = 20
POSTURE_RESTRICTED_TERM = 10

TA_DESK_MAX_SENSITIVITY = 50
DISCLOSURE_COMMITTEE_MIN_SENSITIVITY = 60
ESCALATION_THRESHOLD = 80

MAX_REVISION_ROUNDS = 3

TIER_POINTS = {"TIER_1": 50, "TIER_2": 35, "TIER_3": 20, "UNTIERED": 5}
NDA_BONUS = Decimal(8)
ENGAGEMENT_CAP = Decimal(20)
ENGAGEMENT_MULTIPLIER = Decimal(4)
ACTIVIST_PENALTY = Decimal(15)
TYPE_MULT = {
    "INSTITUTIONAL_HOLDER": Decimal("1.20"),
    "SELL_SIDE_ANALYST": Decimal("1.00"),
    "RETAIL_HOLDER": Decimal("0.60"),
}
LEAD_BONUS_LONG_DAYS = 14
LEAD_BONUS_LONG = Decimal(5)
LEAD_BONUS_SHORT_DAYS = 7
LEAD_BONUS_SHORT = Decimal(2)
MIN_ALLOCATION_SCORE = Decimal(25)
CONTACT_BUFFER_MINUTES = 30

MIN_PAYABLE_LAG_DAYS = 10
REVERSAL_WINDOW_HOURS = 72

ESTIMATE_STALENESS_DAYS = 90
OUTLIER_BAND_PCT = Decimal("0.15")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

__all__ = [n for n in dir() if not n.startswith("__")]
