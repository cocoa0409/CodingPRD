"""Domain thresholds, rates and date helpers for the sales-tax audit API.

Every value here is quoted from the PRD: money is integer cents, rates are
integer basis points, and all date arithmetic is whole-calendar-day arithmetic.
"""
from datetime import date, datetime, timedelta

# --- Global money / rate conventions (PRD 2.6) ---
BP_SCALE = 10_000
STATE_TAX_RATE_BP = 625

# --- Logical clock (PRD 2.5) ---
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_CLOCK_DATE = "2026-08-01"

# --- Selection scoring (PRD 3.1) ---
MAGNITUDE_CAP_CENTS = 5_000_000_000
NEUTRAL_PRIOR_AUDIT_BP = 3_500
DELINQUENCY_BP_PER_PERIOD = 2_500
MAX_DELINQUENT_PERIOD_COUNT = 40
SCORING_WINDOW_DAYS = 1_095
SCREENING_WEIGHTS = {"info_variance_bp": 60, "delinquency_bp": 40}
FULL_WEIGHTS = {
    "info_variance_bp": 35,
    "delinquency_bp": 20,
    "industry_error_rate_bp": 20,
    "magnitude_bp": 15,
    "prior_audit_bp": 10,
}
RISK_SCORE_DIVISOR = 1_000
MAX_RISK_SCORE = 1_000

# --- Statute of limitations (PRD 3.2) ---
BASE_LIMITATION_DAYS = 1_095
EXPIRING_SOON_DAYS = 90

# --- Sampling methodology (PRD 3.3) ---
ALLOWED_CONFIDENCE_LEVELS_BP = (9_000, 9_500, 9_900)
MIN_STRATA = 1
MAX_STRATA = 12
MAX_NEGOTIATION_ROUNDS = 3

# --- Assessment rollup (PRD 3.6) ---
FRAUD_PENALTY_RATE_BP = 5_000
PENALTY_TIER_THRESHOLDS_CENTS = (1_000_000_000, 100_000_000, 1_000_000)
PENALTY_TIER_RATES_BP = (2_500, 1_500, 1_000)
PENALTY_BASE_RATE_BP = 500
ANNUAL_INTEREST_RATE_BP = 800
INTEREST_DAYS_PER_YEAR = 365
SMALL_BALANCE_CEILING_CENTS = 5_000
PROTEST_WINDOW_DAYS = 60

# --- Abatement (PRD 3.7) ---
ABATEMENT_FACTOR_POINTS = {
    "FIRST_TIME_COMPLIANT": 40,
    "RELIANCE_ON_WRITTEN_ADVICE": 35,
    "RECORDS_LOST_IN_DISASTER": 25,
    "SUBSTANTIAL_COOPERATION": 20,
}
MAX_ABATEMENT_PCT = 100
DELINQUENT_ABATEMENT_CAP_PCT = 50

# --- Appeal ladder (PRD 3.8) ---
FORUM_LADDER = ("INFORMAL_CONFERENCE", "ADMINISTRATIVE_APPEAL", "TAX_TRIBUNAL")
ESCALATION_WINDOW_DAYS = 30

# --- Collection (PRD 3.9) ---
COLLECTION_FEE_RATE_BP = 1_000
OIC_MINIMUM_RATE_BP = 2_000
MIN_TERM_MONTHS = 1
MAX_TERM_MONTHS = 72

# --- Use-tax analysis (PRD 3.5) ---
CAPITAL_ASSET_STEPDOWN_MIN_MONTHS = 6
MAX_MONTHS_USED_OUTSIDE_STATE = 600
DEFAULT_IN_STATE_USAGE_PCT_BP = 10_000

# --- Pagination (PRD 2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Operator identities used across fixtures ---
LEAD_AUDITOR_USER_ID = "auditor-1"
OTHER_AUDITOR_USER_ID = "auditor-2"
SUPERVISOR_USER_ID = "supervisor-1"
APPEALS_OFFICER_USER_ID = "appeals-officer-1"
OTHER_APPEALS_OFFICER_USER_ID = "appeals-officer-2"
TRIBUNAL_JUDGE_USER_ID = "tribunal-judge-1"
COLLECTIONS_AGENT_USER_ID = "collections-agent-1"
SELECTION_ANALYST_USER_ID = "selection-analyst-1"


# --- Integer arithmetic helpers (PRD 2.6: round half up, never float) ---

def round_half_up(numerator: int, denominator: int) -> int:
    """Integer division rounded half up, exactly as PRD 2.6 requires."""
    assert denominator > 0, "denominator must be positive"
    if numerator >= 0:
        return (numerator * 2 + denominator) // (denominator * 2)
    return -((-numerator * 2 + denominator) // (denominator * 2))


def tax_on(amount_cents: int) -> int:
    """State sales-and-use tax on an amount: amount * 625 / 10000, half up."""
    return round_half_up(amount_cents * STATE_TAX_RATE_BP, BP_SCALE)


def purchase_price_for_use_tax(target_tax_cents: int) -> int:
    """Purchase price whose 625-bp tax is exactly `target_tax_cents`."""
    return target_tax_cents * (BP_SCALE // STATE_TAX_RATE_BP)


def penalty_rate_for(tax_deficiency_cents: int, fraud_indicator: bool = False) -> int:
    """Penalty rate in basis points under the PRD 3.6 step-two tier table."""
    if fraud_indicator:
        return FRAUD_PENALTY_RATE_BP
    for threshold, rate in zip(PENALTY_TIER_THRESHOLDS_CENTS, PENALTY_TIER_RATES_BP):
        if tax_deficiency_cents > threshold:
            return rate
    return PENALTY_BASE_RATE_BP


# --- Whole-calendar-day date helpers (PRD 2.5) ---

def parse_date(value: str) -> date:
    """Accept either a bare calendar date or a full ISO 8601 instant."""
    text = value.strip()
    if len(text) == 10:
        return date.fromisoformat(text)
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def add_days(value: str, days: int) -> str:
    """Return the calendar date `days` after `value`, as YYYY-MM-DD."""
    return (parse_date(value) + timedelta(days=days)).isoformat()


def days_between(start: str, end: str) -> int:
    """Whole number of calendar days from `start` to `end` (may be negative)."""
    return (parse_date(end) - parse_date(start)).days


def clock_instant(day: str, time_of_day: str = "T00:00:00Z") -> str:
    """Build a logical-clock instant on the given calendar date."""
    return f"{parse_date(day).isoformat()}{time_of_day}"
