"""Domain constants for the Minor League Affiliation & Player Development API.

Every value here is taken verbatim from the PRD; nothing is invented.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- Logical clock (PRD 2.5) -------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# --- Curriculum (PRD 2.11) ---------------------------------------------------
ORG_CURRICULUM_VERSION = "2026.1"

# --- Affiliate registration (PRD 3.1) ---------------------------------------
MEAL_STIPEND_MIN_CENTS = 2500

COMPETITION_LEVELS = (
    "TRIPLE_A",
    "DOUBLE_A",
    "HIGH_A",
    "SINGLE_A",
    "COMPLEX",
    "DOMINICAN_ACADEMY",
)

LEVEL_ROSTER_LIMIT = {
    "TRIPLE_A": 28,
    "DOUBLE_A": 28,
    "HIGH_A": 30,
    "SINGLE_A": 30,
    "COMPLEX": 35,
    "DOMINICAN_ACADEMY": 40,
}

DEFAULT_RESERVE_SLOTS = 35
DEFAULT_HOUSING_BEDS = 40
DEFAULT_TRAVEL_STANDARD_TIER = "BUS_STANDARD"
TRAVEL_STANDARD_TIERS = ("CHARTER", "BUS_SLEEPER", "BUS_STANDARD")

FACILITY_CATEGORIES = (
    "CLUBHOUSE",
    "WEIGHT_ROOM",
    "FIELD_SURFACE",
    "LIGHTING",
    "MEDICAL_ROOM",
    "HOUSING",
    "MEALS",
    "TRAVEL",
)

# --- Facility standing (PRD 2.9) --------------------------------------------
DEFICIENCY_NONE_MIN_SCORE = 85
DEFICIENCY_MINOR_MIN_SCORE = 70
FACILITY_SCORE_NO_REVIEW = "100.00"
REMEDIATION_DAYS = {"MAJOR": 30, "MINOR": 60}
REOPEN_REMEDIATION_DAYS = 15
MAX_REOPEN_COUNT = 2

# --- Agreements (PRD 3.2) ---------------------------------------------------
DEFAULT_MINIMUM_ACTIVE_PLAYERS = 22
FACILITY_STANDARD_TIERS = ("TIER_1", "TIER_2", "TIER_3")
STAFF_ROLES = (
    "HITTING_COACH",
    "PITCHING_COACH",
    "ATHLETIC_TRAINER",
    "STRENGTH_COACH",
    "MANAGER",
)

# --- Expense allocation (PRD 3.3) -------------------------------------------
EXPENSE_CATEGORY_ORDER = ("HOUSING", "MEALS", "TRAVEL", "FACILITY_UPKEEP")
CLUB_SHARES = {
    "HOUSING": Decimal("0.75"),
    "MEALS": Decimal("0.60"),
    "TRAVEL": Decimal("1.00"),
    "FACILITY_UPKEEP": Decimal("0.25"),
}
CLUB_SHARE_SUM = Decimal("2.60")

# --- Staff (PRD 3.4) --------------------------------------------------------
STAFF_DISCIPLINES = ("HITTING", "PITCHING", "ATHLETIC_TRAINING", "STRENGTH", "MANAGEMENT")
MAX_STAFF_FTE_PCT = 100

# --- Players and clearances (PRD 3.5) ---------------------------------------
PLAYER_ORIGINS = ("DOMESTIC_DRAFT", "INTERNATIONAL_FA", "FOREIGN_PRO")
CLEARANCE_TYPES = ("LEVEL_ASSIGNMENT", "REHAB_START", "REHAB_COMPLETE")
DOMESTIC_RESERVE_ORIGINS = ("DOMESTIC_DRAFT", "FOREIGN_PRO")

# --- Assignments and option years (PRD 3.6) ---------------------------------
ASSIGNMENT_TYPES = ("LEVEL", "COMPLEX", "REHAB")
MOVEMENT_REASONS = ("INITIAL", "PROMOTION", "DEMOTION", "REHAB_START", "LATERAL")
DEFAULT_WORKLOAD_CEILING_INDEX = "12.00"
OPTION_YEARS_TOTAL = 3
OPTION_YEAR_MIN_DAYS = 20
REHAB_SLOT_LIMIT = 3
TRANSFER_BUFFER_DAYS = 2

# --- Development plans and workload (PRD 3.7) -------------------------------
DEFAULT_WORKLOAD_LIMIT_WEEKLY_INDEX = "1.50"
MAX_WORKLOAD_LIMIT_WEEKLY_INDEX = "10.00"
WORKLOAD_WINDOW_DAYS = 14
WORKLOAD_INDEX_CEILING = Decimal("25.00")
WORKLOAD_PITCH_WEIGHT = Decimal("0.55")
WORKLOAD_PITCH_DIVISOR = Decimal("100")
WORKLOAD_INNINGS_WEIGHT = Decimal("0.30")
WORKLOAD_INNINGS_DIVISOR = Decimal("10")
WORKLOAD_MINUTES_WEIGHT = Decimal("0.15")
WORKLOAD_MINUTES_DIVISOR = Decimal("60")
REHAB_OUTING_PROJECTED_WEIGHT = Decimal("0.50")

LEVEL_MULTIPLIER = {
    "SINGLE_A": Decimal("1.00"),
    "HIGH_A": Decimal("1.05"),
    "DOUBLE_A": Decimal("1.12"),
    "TRIPLE_A": Decimal("1.18"),
    "COMPLEX": Decimal("1.25"),
    "DOMINICAN_ACADEMY": Decimal("1.30"),
}

PROMOTION_MODULE_WEIGHT = Decimal("0.40")
PROMOTION_HEADROOM_WEIGHT = Decimal("0.25")
PROMOTION_SERVICE_WEIGHT = Decimal("0.35")
PROMOTION_PRESSURE_HORIZON = Decimal("2")
PROMOTION_SERVICE_DAYS_DIVISOR = Decimal("120")
PROMOTION_READINESS_THRESHOLD = Decimal("0.7500")
PROMOTION_SERVICE_DAYS_REQUIRED = 120
MAX_REVIEW_CYCLE_COUNT = 3
MAX_CURRICULUM_MODULES = 12

LEVEL_RANK = {
    "DOMINICAN_ACADEMY": 1,
    "COMPLEX": 2,
    "SINGLE_A": 3,
    "HIGH_A": 4,
    "DOUBLE_A": 5,
    "TRIPLE_A": 6,
}

# --- Transaction reports (PRD 3.8) ------------------------------------------
FILING_DEADLINE_DAYS = 2
LATE_FEE_TIER1_CENTS_PER_DAY = 5000
LATE_FEE_TIER1_DAYS = 2
LATE_FEE_TIER2_CENTS_PER_DAY = 15000
LATE_FEE_TIER2_DAYS = 5
LATE_FEE_TIER3_CENTS_PER_DAY = 30000
MAX_REFILE_COUNT = 2

TRANSACTION_TYPES = (
    "OPTIONAL_ASSIGNMENT",
    "PROMOTION",
    "REHAB_ASSIGNMENT",
    "REHAB_COMPLETE",
    "RECALL",
    "REVOCATION",
)

# --- Signing pool (PRD 3.9) -------------------------------------------------
POOL_TIER_1_CEILING_CENTS = 500000
POOL_TIER_2_CEILING_CENTS = 1000000
POOL_TIER_1_RATE = Decimal("0.75")
POOL_TIER_2_RATE = Decimal("1.00")
POOL_TIER_3_RATE = Decimal("1.00")
POOL_TIER3_FORFEIT_CENTS = 250000
SIGNING_REJECTION_REASONS = ("POOL_HARD_CAPPED", "COMPLIANCE_DENIED")


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    """Round a Decimal half-up to `places` decimal places (PRD 2.8)."""
    exponent = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def tier_tax_cents(overage_cents: int) -> Decimal:
    """Marginal overage tax on an overage amount (PRD 3.9)."""
    overage = Decimal(overage_cents)
    tier1 = min(overage, Decimal(POOL_TIER_1_CEILING_CENTS))
    tier2 = min(
        max(overage - Decimal(POOL_TIER_1_CEILING_CENTS), Decimal(0)),
        Decimal(POOL_TIER_2_CEILING_CENTS - POOL_TIER_1_CEILING_CENTS),
    )
    tier3 = max(overage - Decimal(POOL_TIER_2_CEILING_CENTS), Decimal(0))
    return (
        POOL_TIER_1_RATE * tier1 + POOL_TIER_2_RATE * tier2 + POOL_TIER_3_RATE * tier3
    )


def late_fee_cents(days_late: int) -> int:
    """Three-tier marginal late fee (PRD 3.8)."""
    days = max(0, int(days_late))
    tier1 = LATE_FEE_TIER1_CENTS_PER_DAY * min(days, LATE_FEE_TIER1_DAYS)
    tier2 = LATE_FEE_TIER2_CENTS_PER_DAY * max(
        0, min(days - LATE_FEE_TIER1_DAYS, LATE_FEE_TIER2_DAYS)
    )
    tier3 = LATE_FEE_TIER3_CENTS_PER_DAY * max(0, days - 7)
    return tier1 + tier2 + tier3
