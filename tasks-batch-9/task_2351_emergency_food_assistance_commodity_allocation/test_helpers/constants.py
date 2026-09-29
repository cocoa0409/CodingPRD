"""Domain thresholds and fixed instants declared by the PRD."""

# PRD §2.4 — the logical clock starts at this fixed instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# PRD §2.3 — pagination defaults and bounds.
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# PRD §3.2 — training validity and the post-expiry grace period.
TRAINING_VALIDITY_DAYS = 365
AGREEMENT_GRACE_DAYS = 90

# PRD §3.3 — monitor scoring.
DAYS_ON_HAND_SECONDS_PER_DAY = 86400
AGE_HORIZON_DAYS = 90
TURNOVER_WEIGHT_UNSOLD = 0.70
TURNOVER_WEIGHT_AGE = 0.30
SHELF_LIFE_WEIGHT_CONSUMED = 0.5
SHELF_LIFE_WEIGHT_UNSOLD = 0.5
SLOW_MOVING_THRESHOLD = 0.60

# PRD §3.4 — allocation formula weights and the programme minimum.
POVERTY_WEIGHT = 0.6
PRIOR_WEIGHT = 0.4
HOLD_HARMLESS_FLOOR_RATIO = 0.9
MIN_ALLOCATION_CASES = 5

# PRD §3.7 — dock turnaround buffer, applied on both sides of every peer window.
DOCK_TURNAROUND_MINUTES = 30

# PRD §3.9 — the self-declaration income test.
HOUSEHOLD_BASE_INCOME_LIMIT_CENTS = 195000
HOUSEHOLD_PER_PERSON_INCREMENT_CENTS = 68000
MIN_HOUSEHOLD_SIZE = 1
MAX_HOUSEHOLD_SIZE = 20

# PRD §3.9 — administrative funds withholding.
COMPLIANCE_MINIMUM_PCT = 0.9500
WITHHOLDING_RATE = 0.10

# Precision (PRD §2.7).
POUNDS_DECIMALS = 2
FOUR_DECIMALS = 4
SIX_DECIMALS = 6

# Absolute tolerance used when comparing two-decimal pound figures.
POUNDS_TOLERANCE = 0.01
# Absolute tolerance used when comparing four/six-decimal ratio figures.
RATIO_TOLERANCE = 0.000001


def household_income_limit_cents(household_size: int) -> int:
    """PRD §3.9: base limit plus the per-person increment for each person beyond the first."""
    return (
        HOUSEHOLD_BASE_INCOME_LIMIT_CENTS
        + HOUSEHOLD_PER_PERSON_INCREMENT_CENTS * (household_size - 1)
    )
