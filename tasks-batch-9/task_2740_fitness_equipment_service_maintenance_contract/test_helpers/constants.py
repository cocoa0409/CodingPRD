"""
Business constants declared by the FleetCare PRD.

Every value here is copied from a numbered rule in the PRD; nothing is invented.
Tests import these instead of hard-coding magic numbers so that a reader can see
which contractual table a literal came from.
"""

from decimal import ROUND_HALF_UP, Decimal

# ─── Paths ────────────────────────────────────────────────────────────────────

BUSINESS_PREFIX = "/fleetcare"
CLOCK_PATH = "/_clock/set_current_utc"

# ─── The logical service clock ────────────────────────────────────────────────

# "On startup the logical clock reads exactly 2026-08-01T00:00:00Z".
STARTUP_CLOCK = "2026-08-01T00:00:00Z"

# ─── Pagination ───────────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ─── Enumerations ─────────────────────────────────────────────────────────────

EQUIPMENT_CATEGORIES = ("TREADMILL", "ELLIPTICAL", "BIKE", "STRENGTH")
COVERAGE_TIERS = ("BRONZE", "SILVER", "GOLD")
PARTS_INCLUSIONS = ("NONE", "WEAR_ONLY", "FULL")
PART_CATEGORIES = ("CONSUMABLE", "WEAR", "STRUCTURAL", "ELECTRONIC")
PART_SOURCES = ("NEW", "REFURBISHED", "LOANER_SWAP")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
DUTY_STATUSES = ("ON_DUTY", "OFF_DUTY")
LOCKOUT_REASONS = (
    "INSPECTOR_TAG_OUT",
    "SAFETY_DOC_REJECTED",
    "SAFETY_CRITICAL_FAIL",
    "MEMBER_INJURY",
)
CHECKLIST_RESULTS = ("PASS", "FAIL")

CONTRACT_STATUSES = (
    "DRAFT",
    "ACTIVE",
    "SUSPENDED",
    "RENEWAL_QUOTED",
    "RENEWED",
    "EXPIRED",
)
CALL_STATUSES = ("OPEN", "DISPATCHED", "ON_SITE", "PARTS_HOLD", "RESOLVED", "CANCELLED")
VISIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "MISSED", "CANCELLED")
SAFETY_DOC_STATUSES = ("PENDING", "SUBMITTED", "CERTIFIED", "REJECTED")
ASSIGNMENT_STATUSES = ("RESERVED", "CONFIRMED", "COMPLETED", "RELEASED")
PART_LIFECYCLE_STATUSES = ("ACTIVE", "END_OF_SUPPORT_ANNOUNCED", "OBSOLETE")
PART_ORDER_STATUSES = ("ALLOCATED", "INSTALLED", "CANCELLED")
DOWNTIME_STATUSES = ("OPEN", "CLOSED", "RECONCILED", "WAIVED")
QUOTE_STATUSES = ("ISSUED", "ACCEPTED", "DECLINED", "SUPERSEDED")
EQUIPMENT_LIFECYCLE_STATUSES = ("IN_SERVICE", "DOWN", "TAGGED_OUT")
SUPPORT_STATUSES = ("SUPPORTED", "END_OF_SUPPORT_ANNOUNCED", "UNSUPPORTED")
PM_STATUSES = ("OK", "DUE", "OVERDUE")
FLEET_RISKS = ("LOW", "MODERATE", "HIGH")

# ─── Declared defaults (§3.1, §3.3) ───────────────────────────────────────────

CLUB_DEFAULT_OPEN_MINUTE = 300
CLUB_DEFAULT_CLOSE_MINUTE = 1380
CLUB_DEFAULT_MAX_CONCURRENT_VISITS = 1
TECHNICIAN_DEFAULT_MAX_COMMITTED_MINUTES = 480
TECHNICIAN_DEFAULT_IS_SAFETY_INSPECTOR = False
PART_DEFAULT_IS_CRITICAL_SPARE = False
PART_DEFAULT_ON_HAND_QTY = 0
PART_DEFAULT_REFURB_QTY = 0
EQUIPMENT_DEFAULT_INITIAL_USAGE_HOURS = 0
MODEL_DEFAULT_CHECKLIST_TEMPLATE: tuple = ()

# ─── Contract drafting tables (§3.2) ──────────────────────────────────────────

# "eight hours (480 minutes) on BRONZE, four hours (240 minutes) on SILVER,
#  two hours (120 minutes) on GOLD".
SLA_RESPONSE_MINUTES = {"BRONZE": 480, "SILVER": 240, "GOLD": 120}

# "at least one visit a year on BRONZE, at least two on SILVER, at least four on GOLD".
TIER_MIN_PM_VISITS = {"BRONZE": 1, "SILVER": 2, "GOLD": 4}

# "BRONZE may be sold only with NONE or WEAR_ONLY, and FULL requires SILVER or GOLD".
TIER_ALLOWED_PARTS_INCLUSION = {
    "BRONZE": ("NONE", "WEAR_ONLY"),
    "SILVER": ("NONE", "WEAR_ONLY", "FULL"),
    "GOLD": ("NONE", "WEAR_ONLY", "FULL"),
}

# "credit_cap_cents ... is fifteen percent of annual_base_cents".
CREDIT_CAP_PCT = Decimal("0.15")

# ─── Service-call tables (§3.6) ───────────────────────────────────────────────

SEVERITY_SLA_FACTOR = {
    "CRITICAL": Decimal("0.5"),
    "MAJOR": Decimal("1.0"),
    "MINOR": Decimal("2.0"),
}
SEVERITY_PLANNED_MINUTES = {"CRITICAL": 180, "MAJOR": 120, "MINOR": 60}
MAX_PARTS_HOLD_COUNT = 3

# ─── Technician calendar (§3.3) ───────────────────────────────────────────────

TRAVEL_BUFFER_MINUTES = 45
MAX_VISIT_WINDOW_MINUTES = 480

# ─── Preventive maintenance (§3.1, §3.4) ──────────────────────────────────────

PM_DUE_FACTOR = Decimal("1.00")
PM_OVERDUE_FACTOR = Decimal("1.25")
PM_COMPLIANCE_EMPTY_HISTORY_PCT = Decimal("100.00")
MAX_CHECKLIST_TEMPLATE_ELEMENTS = 20

# ─── Parts pricing (§3.7) ─────────────────────────────────────────────────────

SOURCE_PRICE_FACTOR = {
    "NEW": Decimal("1.00"),
    "REFURBISHED": Decimal("0.60"),
    "LOANER_SWAP": Decimal("0.00"),
}
# "NEW draws on on_hand_qty while both REFURBISHED and LOANER_SWAP draw on
#  refurb_on_hand_qty".
SOURCE_STOCK_BUCKET = {
    "NEW": "on_hand_qty",
    "REFURBISHED": "refurb_on_hand_qty",
    "LOANER_SWAP": "refurb_on_hand_qty",
}
WEAR_ONLY_COVERED_CATEGORY = "WEAR"

# ─── Downtime credit tables (§3.8) ────────────────────────────────────────────

DOWNTIME_GRACE_MINUTES = {"BRONZE": 720, "SILVER": 360, "GOLD": 180}
DOWNTIME_RATE_CENTS_PER_HOUR = {"BRONZE": 400, "SILVER": 900, "GOLD": 1600}

# ─── Health scoring and fleet risk (§3.9) ─────────────────────────────────────

FAILURE_VARIANT_MIN_RESOLVED_CALLS = 3
FAILURE_LOOKBACK_DAYS = 365
HEALTH_AGE_POINTS_PER_YEAR = 2
HEALTH_CRITICAL_WEIGHT = 8
HEALTH_MAJOR_WEIGHT = 4
HEALTH_MINOR_WEIGHT = 2
HEALTH_MIN = Decimal("0.00")
HEALTH_MAX = Decimal("100.00")
REPLACEMENT_THRESHOLD_DEFAULT = Decimal("40.00")
REPLACEMENT_THRESHOLD_UNSUPPORTED = Decimal("60.00")
FLEET_RISK_HIGH_RATIO = Decimal("0.30")
FLEET_RISK_MODERATE_RATIO = Decimal("0.15")

# ─── Renewal quote pricing (§3.9) ─────────────────────────────────────────────

# Step table: 1.00 for 0-2 years, 1.15 for 3-5, 1.35 for 6-8, 1.60 for 9 or more.
AGE_MULTIPLIER_BANDS = (
    (0, 2, Decimal("1.00")),
    (3, 5, Decimal("1.15")),
    (6, 8, Decimal("1.35")),
    (9, None, Decimal("1.60")),
)
CONDITION_ADDER_REPLACEMENT_RECOMMENDED = Decimal("0.25")
CONDITION_ADDER_UNSUPPORTED = Decimal("0.20")
CONDITION_ADDER_EOS_ANNOUNCED = Decimal("0.10")
PARTS_SURCHARGE_PCT = {
    "NONE": Decimal("0.00"),
    "WEAR_ONLY": Decimal("0.08"),
    "FULL": Decimal("0.18"),
}
HISTORY_LOAD_PER_SLA_BREACH = Decimal("0.03")
HISTORY_LOAD_PER_CRITICAL_CALL = Decimal("0.015")
HISTORY_LOAD_CAP = Decimal("0.25")
COMPLIANCE_DISCOUNT_HIGH_THRESHOLD = Decimal("90.00")
COMPLIANCE_DISCOUNT_HIGH_PCT = Decimal("0.05")
COMPLIANCE_DISCOUNT_MID_THRESHOLD = Decimal("75.00")
COMPLIANCE_DISCOUNT_MID_PCT = Decimal("0.02")
COMPLIANCE_DISCOUNT_NONE_PCT = Decimal("0.00")
COLLAR_FLOOR_PCT = Decimal("0.90")
COLLAR_CAP_PCT = Decimal("1.35")
QUOTE_VALIDITY_DAYS = 30

# ─── Test-only literals ───────────────────────────────────────────────────────

# A syntactically valid UUID that names no row in any collection.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

MONEY_TOLERANCE = 0
DECIMAL_TOLERANCE = 0.01


def round_half_up(value, places: int = 0):
    """Round a numeric value half-up to ``places`` decimals, as the PRD requires."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


def round_half_up_cents(value) -> int:
    """Round a monetary expression half-up to whole cents and return an int."""
    return int(round_half_up(value, 0))
