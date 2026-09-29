"""Core primitives: logical clock, in-memory store, id/time/rounding helpers, constants.

NOTE: the store is plain in-process Python dicts and starts completely EMPTY on
every boot. Nothing is seeded, preloaded or hardcoded here.
"""
import itertools
import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

UTC = timezone.utc

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class LogicalClock(object):
    def __init__(self):
        self._now = CLOCK_EPOCH

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(UTC)
        return self._now


clock = LogicalClock()

# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
_seq_counter = itertools.count(1)

LOCK = threading.RLock()


class Store(object):
    """Plain in-memory dictionaries, keyed by id."""

    def __init__(self):
        self.members = {}
        self.stratifications = {}
        self.programs = {}
        self.care_managers = {}
        self.enrollments = {}
        self.care_plans = {}
        self.goals = {}
        self.interventions = {}
        self.touches = {}
        self.transition_events = {}
        self.social_needs = {}
        self.community_resources = {}
        self.referrals = {}
        self.roi_measurements = {}


db = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    return fmt_instant(datetime.now(UTC))


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date string; returns a date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_str(dt):
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_hours(dt, hours):
    return dt + timedelta(hours=float(hours))


def month_start(dt):
    dt = dt.astimezone(UTC)
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def add_months(dt, months):
    y = dt.year
    m = dt.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return datetime(y, m, 1, tzinfo=UTC)


# --------------------------------------------------------------------------
# Rounding helpers
# --------------------------------------------------------------------------
def rhu(value, places=0):
    """Round half up (away from zero at the midpoint) to `places` decimals."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def trunc_toward_zero(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_DOWN))


def dec_to_float(value):
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------
# Domain constants
# --------------------------------------------------------------------------
ROLES = ["ProgramAdmin", "CareManager", "ClinicalReviewer",
         "UtilizationAnalyst", "CommunityPartner"]

TIER_ORDER = {"LOW": 0, "MODERATE": 1, "RISING": 2, "HIGH": 3}
TIERS = ["LOW", "MODERATE", "RISING", "HIGH"]

TIER_POINTS = {
    "LOW": Decimal("1"),
    "MODERATE": Decimal("2"),
    "RISING": Decimal("4"),
    "HIGH": Decimal("7"),
}

CADENCE_MULTIPLIER = {
    "STANDARD": Decimal("1.0"),
    "INTENSIVE": Decimal("1.5"),
    "TOC_INTENSIVE": Decimal("2.0"),
}

CADENCE_INTERVAL_DAYS = {
    "STANDARD": 30,
    "INTENSIVE": 14,
    "TOC_INTENSIVE": 7,
}

CREDENTIAL_LEVELS = ["RN", "LCSW", "CHW"]
STRAT_VARIANTS = ["CONCURRENT", "PROSPECTIVE"]
CONSENT_STATUSES = ["GRANTED", "REVOKED"]
EVENT_TYPES = ["INPATIENT_ADMISSION", "ED_VISIT", "OBSERVATION_STAY",
               "SCHEDULED_ADMISSION", "DISCHARGE"]
ADJUDICATION_STATUSES = ["OPEN", "CLOSED"]
DISCHARGE_DISPOSITIONS = ["HOME", "SNF", "HOME_HEALTH", "AMA", "EXPIRED"]
ENROLLMENT_STATUSES = ["PENDING", "ACTIVE", "GRADUATED", "DISENROLLED"]
ENGAGEMENT_STATUSES = ["UNREACHED", "ENGAGED", "AT_RISK", "DISENGAGED"]
CADENCE_TIERS = ["STANDARD", "INTENSIVE", "TOC_INTENSIVE"]
DISENROLL_REASONS = ["GOALS_MET", "LOST_CONTACT", "MEMBER_REQUEST",
                     "INELIGIBLE", "DECEASED"]
CARE_PLAN_STATUSES = ["DRAFT", "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "CLOSED"]
GOAL_DOMAINS = ["CLINICAL", "MEDICATION", "BEHAVIORAL", "FOOD", "HOUSING",
                "TRANSPORTATION", "UTILITIES"]
GOAL_STATUSES = ["OPEN", "AT_RISK", "MET", "CLOSED_UNMET"]
INTERVENTION_MODALITIES = ["PHONE", "HOME_VISIT", "EDUCATION",
                           "REFERRAL_COORDINATION", "MEDICATION_REVIEW"]
INTERVENTION_STATUSES = ["PLANNED", "COMPLETED", "VOIDED"]
TOUCH_TYPES = ["ROUTINE", "TOC", "ASSESSMENT"]
TOUCH_MODALITIES = ["PHONE", "VIDEO", "HOME_VISIT"]
TOUCH_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
TOUCH_OUTCOMES = ["REACHED", "NOT_REACHED"]
SOCIAL_DOMAINS = ["FOOD", "HOUSING", "TRANSPORTATION", "UTILITIES"]
SEVERITIES = ["LOW", "MODERATE", "SEVERE"]
SOCIAL_NEED_STATUSES = ["IDENTIFIED", "REFERRED", "RESOLVED", "UNMET_ESCALATED"]
CONTRACT_STATUSES = ["CONTRACTED", "NOT_CONTRACTED", "SUSPENDED"]
REFERRAL_STATUSES = ["SENT", "ACCEPTED", "DECLINED", "CLOSED_MET", "CLOSED_UNMET"]
REVIEW_DECISIONS = ["APPROVE", "REQUEST_REVISION"]
RESOLUTIONS = ["SERVICE_DELIVERED", "SERVICE_NOT_DELIVERED"]
DECISIONS = ["ACCEPT", "DECLINE"]
ROI_METHODS = ["PRE_POST", "MATCHED_COHORT"]
CAPACITY_STATUSES = ["OPEN", "OVER_CAPACITY"]

# stratification
LOOKBACK_DAYS = 180
FORWARD_DAYS = 90
RECENCY_FULL_DAYS = Decimal("90")
RECENCY_DECAY_FACTOR = Decimal("0.5")
EVENT_POINTS = {
    "INPATIENT_ADMISSION": Decimal("20"),
    "ED_VISIT": Decimal("8"),
    "OBSERVATION_STAY": Decimal("5"),
    "SCHEDULED_ADMISSION": Decimal("20"),
}
CHRONIC_POINT_VALUE = Decimal("6")
SDOH_POINT_VALUE = Decimal("4")
SDOH_POINT_CAP = Decimal("12")

# engagement
ENGAGEMENT_WINDOW_DAYS = 90
ENGAGED_SCORE_MIN = 60
DISENGAGE_FAILED_TOUCH_THRESHOLD = 3

# next-touch projection
ESCALATION_FAILED_TOUCH_MIN = 2
MIN_INTERVAL_DAYS = 3
ENGAGED_RELAXATION_DAYS = 7
MAX_INTERVAL_DAYS = 45
TOC_CONTACT_INTERVAL_DAYS = 2

# scheduling
DOCUMENTATION_BUFFER_MINUTES = 15

# roi
TREND_FACTOR = Decimal("1.03")
BASELINE_MONTHS = 12
COHORT_RISK_FACTOR = {
    "LOW": Decimal("0.6"),
    "MODERATE": Decimal("1.0"),
    "RISING": Decimal("1.4"),
    "HIGH": Decimal("2.1"),
}

DEFICIENCY_CODES = [
    "CARE_PLAN_MISSING",
    "CARE_PLAN_STALE",
    "TOUCH_OVERDUE",
    "TOC_OUTREACH_MISSED",
    "REFERRAL_LOOP_OPEN",
    "MISSING_CONTACT_NOTE",
]
