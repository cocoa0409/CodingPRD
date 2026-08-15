"""Declared constants, enum member sets and domain tables.

Every value traces to PRD sections 2-3 (mirrored in SCAFFOLD.yaml).
"""

# ---------------------------------------------------------------- roles / auth
ROLES = (
    "OrgRequester",
    "Scheduler",
    "ServiceCoordinator",
    "FacilitiesManager",
    "FinanceAdmin",
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# --------------------------------------------------------------- logical clock
# PRD 2.4: before any adjustment the server clock starts at exactly this instant
# and never falls back to wall-clock time.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ------------------------------------------------------------------ pagination
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0

# ------------------------------------------------------------------ vocabularies
ORG_TYPES = ("INTERNAL_DEPARTMENT", "STUDENT_GROUP", "EXTERNAL")

FEATURES = (
    "PROJECTOR",
    "VIDEO_CONF",
    "SOUND_SYSTEM",
    "STAGE",
    "PIANO",
    "LAB_BENCHES",
    "KITCHEN_ACCESS",
    "ADA_LIFT",
)

# PRD 3.3 priority_score feature weights.
FEATURE_WEIGHTS = {
    "PIANO": 50,
    "STAGE": 40,
    "LAB_BENCHES": 30,
    "KITCHEN_ACCESS": 25,
    "VIDEO_CONF": 20,
    "SOUND_SYSTEM": 15,
    "PROJECTOR": 10,
    "ADA_LIFT": 5,
}

DAYS_OF_WEEK = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
# datetime.weekday(): Monday == 0 ... Sunday == 6
DAY_TO_WEEKDAY = {name: idx for idx, name in enumerate(DAYS_OF_WEEK)}

SERVICE_CATEGORIES = ("AV", "CATERING", "CUSTODIAL", "SECURITY")

GRANT_TYPES = ("PHYSICAL_KEY", "CARD_ACCESS")

# ------------------------------------------------------------- org precedence
# PRD 3.1: precedence_tier stamped at event creation from org_type.
PRECEDENCE_TIER = {
    "INTERNAL_DEPARTMENT": 200,
    "STUDENT_GROUP": 100,
    "EXTERNAL": 50,
}

# PRD 2.7: which rate card each org_type pays.
RATE_FIELD = {
    "INTERNAL_DEPARTMENT": "internal_hourly_rate_cents",
    "STUDENT_GROUP": "student_hourly_rate_cents",
    "EXTERNAL": "external_hourly_rate_cents",
}

# ------------------------------------------------------------------ standings
STANDING_GOOD = "GOOD"
STANDING_PROBATION = "PROBATION"
STANDING_SUSPENDED = "SUSPENDED"
PROBATION_NO_SHOW_COUNT = 2
SUSPENDED_NO_SHOW_COUNT = 3

# ------------------------------------------------------------------ time rules
DECISION_DEADLINE_HOURS = 72
CONFIRM_WINDOW_HOURS = 48
CHECKIN_EARLY_MINUTES = 30
CHECKIN_LATE_MINUTES = 15
BUMP_SHIELD_HOURS = 72
RETURN_DEADLINE_HOURS = 24
SERVICE_WINDOW_MARGIN_HOURS = 2
MIN_EVENT_MINUTES = 30
MAX_EVENT_HOURS = 8

# ------------------------------------------------------------------ money rules
PEAK_MULTIPLIER_DEFAULT_BPS = 12500
PEAK_HOUR_START = 18  # UTC clock-hour bucket starting >= 18:00 is peak
BPS_DENOMINATOR = 10000

CANCEL_TIER_FREE_HOURS = 72
CANCEL_TIER_HALF_HOURS = 24
CANCEL_TIER_HALF_BPS = 5000
CANCEL_TIER_FULL_BPS = 10000

INSURANCE_SURCHARGE_BPS = 200  # 2%
NO_SHOW_FLAT_FEE_CENTS = 5000
MIN_LIABILITY_COVERAGE_CENTS = 100000000

KEY_DEPOSIT_CENTS = 7500
CARD_DEPOSIT_CENTS = 2500
LATE_RETURN_FORFEIT_BPS = 5000

DEPOSIT_BY_GRANT_TYPE = {
    "PHYSICAL_KEY": KEY_DEPOSIT_CENTS,
    "CARD_ACCESS": CARD_DEPOSIT_CENTS,
}

LARGE_CLASS_BONUS = 100
LARGE_CLASS_THRESHOLD = 100
ENROLLMENT_WEIGHT = 10

# --------------------------------------------------------------- entity states
ORG_STANDINGS = ("GOOD", "PROBATION", "SUSPENDED")
ROOM_STATUSES = ("ACTIVE", "OUT_OF_SERVICE")
TERM_STATUSES = ("DRAFT", "SCHEDULING", "GENERAL", "CLOSED")
BLOCK_STATUSES = ("UNPLACED", "PLACED")
RUN_STATUSES = ("DRAFT", "FINALIZED", "SUPERSEDED")
EVENT_STATUSES = (
    "REQUESTED",
    "APPROVED",
    "CONFIRMED",
    "IN_PROGRESS",
    "COMPLETED",
    "NO_SHOW",
    "CANCELLED",
    "DECLINED",
    "EXPIRED",
    "BUMPED",
)
ORDER_STATUSES = (
    "REQUESTED",
    "QUOTED",
    "NEEDS_REVISION",
    "APPROVED",
    "SCHEDULED",
    "FULFILLED",
    "INVOICED",
    "CANCELLED",
)
INVOICE_STATUSES = (
    "PROVISIONAL",
    "FINALIZED",
    "PARTIALLY_PAID",
    "PAID",
    "VOIDED",
    "REFUNDED",
)
GRANT_STATUSES = ("REQUESTED", "ISSUED", "OVERDUE", "RETURNED", "LOST", "REVOKED")

# Occupying event statuses (PRD 2.6): only these block a room.
OCCUPYING_EVENT_STATUSES = ("APPROVED", "CONFIRMED", "IN_PROGRESS")
# Placement also treats REQUESTED demand as conflicting (SCAFFOLD placement (b)).
PLACEMENT_EVENT_STATUSES = ("REQUESTED", "APPROVED", "CONFIRMED", "IN_PROGRESS")
# Non-terminal service order statuses (terminal: INVOICED, CANCELLED).
ORDER_NONTERMINAL_STATUSES = ("REQUESTED", "QUOTED", "NEEDS_REVISION", "APPROVED", "SCHEDULED")
# Statuses counted in the provisional (forward-looking) service charge.
ORDER_PROVISIONAL_CHARGE_STATUSES = ("QUOTED", "APPROVED", "SCHEDULED", "FULFILLED")
# Statuses counted in the final (actuals) service charge.
ORDER_FINAL_CHARGE_STATUSES = ("FULFILLED", "INVOICED")
# Outstanding-grant statuses (deposits held, bump shield, cancel block).
GRANT_OUTSTANDING_STATUSES = ("ISSUED", "OVERDUE")
# Invoice statuses that count toward outstanding_balance_cents.
INVOICE_OPEN_STATUSES = ("PROVISIONAL", "FINALIZED", "PARTIALLY_PAID")

CANCEL_REASONS = ("CLIENT", "ADMIN", "BUMPED", "ORG_SUSPENDED")
