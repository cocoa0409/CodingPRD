"""Business constants for the Premium Sports Hospitality Packages API.

Every value here is taken from the PRD: the tier multipliers and channel
commission rates of §3.4/§3.5, the volume-discount and guarantee-surcharge
ladders of §3.5, the schedule shape of §3.6, the risk weights and bands of
§3.9, the interval buffers of §2.10 and the cancellation ladders of §3.8.
"""

# --------------------------------------------------------------------------
# Roles (§2.1)
# --------------------------------------------------------------------------
ROLE_RIGHTS_MANAGER = "RightsManager"
ROLE_COMMERCIAL_MANAGER = "CommercialManager"
ROLE_COMMERCIAL_DIRECTOR = "CommercialDirector"
ROLE_CLIENT_SERVICE_AGENT = "ClientServiceAgent"
ROLE_OPERATIONS_MANAGER = "OperationsManager"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_CLIENT_PORTAL_USER = "ClientPortalUser"

ALL_ROLES = [
    ROLE_RIGHTS_MANAGER,
    ROLE_COMMERCIAL_MANAGER,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_CLIENT_SERVICE_AGENT,
    ROLE_OPERATIONS_MANAGER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_CLIENT_PORTAL_USER,
]

# --------------------------------------------------------------------------
# Logical clock (§2.4)
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00.000Z"
SECONDS_PER_DAY = 86400

# --------------------------------------------------------------------------
# Enumerations (§3.1 - §3.7)
# --------------------------------------------------------------------------
SPORTS = ["FOOTBALL", "BASKETBALL", "MOTORSPORT", "TENNIS", "RUGBY"]
EVENT_STATUSES = ["SCHEDULED", "POSTPONED", "RESCHEDULED", "CANCELLED", "COMPLETED"]

INVENTORY_TYPES = ["TICKET", "HOSPITALITY_SPACE", "ACCESS_EXPERIENCE"]
DEAL_STATUSES = [
    "DRAFT",
    "COMMITTED",
    "PARTIALLY_RELEASED",
    "FULLY_RELEASED",
    "SHORTFALL_DECLARED",
    "SETTLED",
    "TERMINATED",
]
TRANCHE_STATES = ["PENDING", "CONFIRMED", "SHORT_CONFIRMED", "LAPSED"]

CHANNELS = ["INDIVIDUAL", "CORPORATE", "TRAVEL_PARTNER"]
BLOCK_STATES = ["OPEN", "EXHAUSTED", "RECALLED"]

TIERS = ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
PACKAGE_STATUSES = ["DRAFT", "PRICED", "PUBLISHED", "CLOSED"]
COMPONENT_TYPES = ["TICKET", "HOTEL", "TRANSPORT", "EXPERIENCE", "CATERING"]

CLIENT_TYPES = ["INDIVIDUAL", "CORPORATE", "TRAVEL_PARTNER"]
CLIENT_STATUSES = ["ACTIVE", "ON_HOLD", "BLOCKED"]

FULFILLMENT_STATUSES = [
    "RESERVED",
    "ALLOCATED",
    "CREDENTIALED",
    "DELIVERED",
    "REBOOK_PENDING",
    "CANCELLED",
]
PAYMENT_STATUSES = [
    "UNPAID",
    "DEPOSIT_PAID",
    "PAID_IN_FULL",
    "SETTLEMENT_DUE",
    "SETTLED",
    "REFUNDED",
]

INSTALLMENT_KINDS = ["SCHEDULE", "SETTLEMENT"]
INSTALLMENT_STATES = ["SCHEDULED", "PAID", "OVERDUE", "VOIDED"]

BUILD_STATES = ["PLANNED", "APPROVED", "READY", "CLOSED", "CANCELLED"]
ASSIGNMENT_STATES = ["ASSIGNED", "RELEASED", "VOIDED"]

SETTLEMENT_VARIANTS = ["TIER_SCHEDULE", "COST_RECOVERY"]
MARGIN_VARIANTS = ["PROVISIONAL", "FINAL"]
RISK_POSTURES = ["NORMAL", "ELEVATED", "CRITICAL"]

# --------------------------------------------------------------------------
# Rights and liability (§3.1)
# --------------------------------------------------------------------------
SHORTFALL_LIABILITY_PCT = 0.60

# --------------------------------------------------------------------------
# Package pricing (§3.4)
# --------------------------------------------------------------------------
TIER_MULTIPLIER = {
    "BRONZE": 1.00,
    "SILVER": 1.10,
    "GOLD": 1.25,
    "PLATINUM": 1.45,
}
DEFAULT_MIN_MARGIN_PCT = 0.25

# --------------------------------------------------------------------------
# Booking price build-up (§3.5)
# --------------------------------------------------------------------------
CHANNEL_COMMISSION_PCT = {
    "INDIVIDUAL": 0.0000,
    "CORPORATE": 0.0300,
    "TRAVEL_PARTNER": 0.1000,
}
# units threshold -> volume discount fraction, evaluated high to low
VOLUME_DISCOUNT_LADDER = [(20, 0.1200), (10, 0.0800), (5, 0.0400)]
VOLUME_DISCOUNT_NONE = 0.0000
# discounted_subtotal_cents threshold -> guarantee surcharge rate, high to low
GUARANTEE_SURCHARGE_LADDER = [(5000000, 0.0200), (1000000, 0.0350)]
GUARANTEE_SURCHARGE_SMALL = 0.0500

# --------------------------------------------------------------------------
# Payment schedule (§3.6)
# --------------------------------------------------------------------------
SCHEDULE_MIN_DAYS = 30
DEPOSIT_PCT = 0.30
SECOND_PCT = 0.40
FIRST_LINE_DAYS = 3
SECOND_LINE_DAYS_BEFORE_EVENT = 90
THIRD_LINE_DAYS_BEFORE_EVENT = 30
SETTLEMENT_DUE_DAYS = 7

# Credit standing bands (§3.6)
ON_HOLD_MIN_OVERDUE = 1
ON_HOLD_MAX_OVERDUE = 2
BLOCKED_MIN_OVERDUE = 3

# --------------------------------------------------------------------------
# Venue and hosts (§2.10, §3.7)
# --------------------------------------------------------------------------
BUILD_BUFFER_MINUTES = 90
DEFAULT_MAX_CONCURRENT_BOOKINGS = 1

# --------------------------------------------------------------------------
# Disruption (§3.8)
# --------------------------------------------------------------------------
REBOOK_WINDOW_DAYS = 21
# days-to-event threshold -> fee percentage, evaluated high to low
TIER_SCHEDULE_LADDER = [(90, 0.10), (60, 0.25), (30, 0.50), (7, 0.80)]
TIER_SCHEDULE_LATE_PCT = 1.00
NON_TICKET_IRRECOVERABLE_PCT = 0.20

# --------------------------------------------------------------------------
# Fulfillment risk and margin (§3.9)
# --------------------------------------------------------------------------
GAP_WEIGHT = 40
LAPSE_WEIGHT = 30
HORIZON_NEAR_WEIGHT = 20
HORIZON_MID_WEIGHT = 10
POSTPONED_WEIGHT = 10
HORIZON_NEAR_DAYS = 14
HORIZON_MID_DAYS = 30
RISK_SCORE_CAP = 100
CRITICAL_THRESHOLD = 70
ELEVATED_THRESHOLD = 40
SALVAGE_RECOVERY_PCT = 0.35

# --------------------------------------------------------------------------
# Pagination (§2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
