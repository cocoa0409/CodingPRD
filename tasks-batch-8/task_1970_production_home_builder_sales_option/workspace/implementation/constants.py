"""Domain constants (SCAFFOLD calculations constants; PRD sections 2.6-2.8, 3.x)."""

from decimal import Decimal

# Roles (PRD section 2.1) — spelled exactly as declared.
ROLE_ANONYMOUS = "Anonymous"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_SALES_DIRECTOR = "SalesDirector"
ROLE_SALES_AGENT = "SalesAgent"
ROLE_BUYER = "Buyer"
ROLE_CONSTRUCTION_MANAGER = "ConstructionManager"

ALL_ROLES = {
    ROLE_ANONYMOUS,
    ROLE_PLATFORM_ADMIN,
    ROLE_SALES_DIRECTOR,
    ROLE_SALES_AGENT,
    ROLE_BUYER,
    ROLE_CONSTRUCTION_MANAGER,
}

# Roles authorized for every GET endpoint (all except Anonymous).
READ_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_SALES_DIRECTOR,
    ROLE_SALES_AGENT,
    ROLE_BUYER,
    ROLE_CONSTRUCTION_MANAGER,
]

# Construction stage calendar (PRD section 2.7): the five build stages in
# order, plus the NOT_STARTED / COMPLETE bookends used by current_stage.
BUILD_STAGES = ["PRE_CONSTRUCTION", "FOUNDATION", "FRAMING", "DRYWALL", "FINAL_WALKTHROUGH"]

STAGE_ORDINAL = {
    "NOT_STARTED": 0,
    "PRE_CONSTRUCTION": 1,
    "FOUNDATION": 2,
    "FRAMING": 3,
    "DRYWALL": 4,
    "FINAL_WALKTHROUGH": 5,
    "COMPLETE": 6,
}

STAGE_DURATIONS_DAYS = {
    "PRE_CONSTRUCTION": 30,
    "FOUNDATION": 21,
    "FRAMING": 28,
    "DRYWALL": 35,
    "FINAL_WALKTHROUGH": 14,
}

CLOSE_BUFFER_DAYS = 7
WEATHER_BUFFER_PCT = Decimal("0.15")

# Lot release pricing (calculation lot_release_pricing).
LOT_TYPE_PREMIUM_CENTS = {
    "STANDARD": 0,
    "CORNER": 1500000,
    "VIEW": 2500000,
    "CUL_DE_SAC": 1000000,
}
LOT_TYPES = set(LOT_TYPE_PREMIUM_CENTS)
PREMIUM_CAP_CENTS = 3000000
RE_RELEASE_UPLIFT_PCT = Decimal("0.02")

# Reservation hold.
HOLD_HOURS = 72

# Option catalog.
OPTION_CATEGORIES = {"STRUCTURAL", "KITCHEN", "BATH", "FLOORING", "ELECTRICAL", "OUTDOOR"}
CHANGE_FEE_PCT = Decimal("0.10")

# Earnest money (calculation earnest_money_refund).
EARNEST_FORFEIT_PCT = Decimal("0.25")
MIN_EARNEST_CENTS = 100000

# Incentives (calculation incentive_budget_ledger).
AUTO_APPROVE_LIMIT_CENTS = 300000
INCENTIVE_CAP_PCT = Decimal("0.06")
INCENTIVE_TYPES = {"RATE_BUYDOWN", "CLOSING_COST_CREDIT", "PRICE_REDUCTION"}

# Warranty (PRD section 3.9).
WARRANTY_TERM_MONTHS = 12

# Contingency trackers.
CONTINGENCY_TYPES = {"financing", "appraisal", "sale_of_home"}
CONTINGENCY_ACTIONS = {"CLEARED", "WAIVED"}

AGREEMENT_CANCEL_REASONS = {"BUYER_DEFAULT", "BUILDER_DEFAULT"}

INCENTIVE_DECIDE_ACTIONS = {"APPROVE", "DENY"}
