"""Domain thresholds and constant tables stated in the PRD."""

from decimal import ROUND_HALF_UP, Decimal

# The logical clock reads exactly this instant at startup.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# Share of current authority a fund type may release in each quarter.
QUARTER_CAP_PCT = {
    "GENERAL": {1: 0.22, 2: 0.26, 3: 0.26, 4: 0.26},
    "FEDERAL": {1: 0.25, 2: 0.25, 3: 0.25, 4: 0.25},
    "DEDICATED": {1: 0.30, 2: 0.30, 3: 0.20, 4: 0.20},
}

# Cumulative statewide cash-flow factor through each quarter.
CASH_FLOW_FACTOR = {1: 0.20, 2: 0.45, 3: 0.70, 4: 1.00}

# Share of current authority a fund type may carry forward at cycle close.
CARRYFORWARD_CAP_PCT = {"GENERAL": 0.00, "FEDERAL": 1.00, "DEDICATED": 0.15}

# Statutory transfer cap: ten percent of the source line's enacted amount.
TRANSFER_AUTHORITY_CAP_PCT = 0.10

# Cash posture flips to CONSTRAINED at this utilization ratio.
CONSTRAINED_UTILIZATION_THRESHOLD = 0.90

# Reported precision of the two ratio fields.
CASH_UTILIZATION_DECIMALS = 4
MOE_COMPLIANCE_RATIO_DECIMALS = 6

# Default configuration percentages.
DEFAULT_CONSTITUTIONAL_RESERVE_PCT = 0.05
DEFAULT_REQUIRED_MATCH_RATIO = 0.25

# Pagination contract.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

TEST_DEFAULTS = {
    "FISCAL_YEAR": 2027,
    "FISCAL_YEAR_START_DATE": "2026-07-01",
    "RESERVE_BALANCE_CENTS": 500_000_000,
    "GENERAL_REVENUE_CENTS": 10_000_000_000,
    "APPROPRIATION_CENTS": 2_000_000_000,
    "BASE_BUDGET_CENTS": 1_000_000_000,
}

# Distinct operator identifiers, required wherever separation of duties applies.
PREPARER_USER_ID = "analyst-1"
APPROVER_USER_ID = "dir-1"
SECOND_APPROVER_USER_ID = "dir-2"


def round_half_up(value) -> int:
    """Round a numeric value to the nearest integer, halves away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_to(value, decimals: int) -> float:
    """Round a numeric value to `decimals` places, halves away from zero."""
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def quarter_cap_cents(current_authority_cents: int, fund_type: str, quarter: int) -> int:
    """The quarter cap: current authority times the fund's permitted share, rounded to the cent."""
    return round_half_up(current_authority_cents * QUARTER_CAP_PCT[fund_type][quarter])


def projected_cumulative_cash_cents(adopted_general_revenue_cents: int, quarter: int) -> int:
    """Adopted general-fund revenue times the quarter's cumulative cash-flow factor."""
    return round_half_up(adopted_general_revenue_cents * CASH_FLOW_FACTOR[quarter])
