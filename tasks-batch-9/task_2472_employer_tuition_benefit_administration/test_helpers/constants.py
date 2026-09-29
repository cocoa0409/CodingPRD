"""
Domain constants for the Employer Tuition Benefit Administration API.

Every value here is taken from the PRD: the statutory exclusion limit and the
grade-bonus / admin-fee / persistence-risk tables of §2.5, §2.10, §3.6 and §3.8,
plus the envelope and clock defaults of §2.3 and §2.4.
"""

from decimal import Decimal, ROUND_HALF_UP

# ─── Logical clock (PRD §2.4) ──────────────────────────────────────────────
# "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# ─── Pagination envelope (PRD §2.3) ────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Educational-assistance tax ledger (PRD §2.10) ─────────────────────────
# "at most 525,000 cents ... may be excluded from an employee's income in a
# calendar year".
TAX_EXCLUSION_LIMIT_CENTS = 525_000

# ─── Reimbursement settlement (PRD §3.6) ───────────────────────────────────
GRADE_BONUS_PCT = 0.10
GRADE_BONUS_MIN_POINTS = 3.50
EFFECTIVE_PCT_CAP = 1.00

ADMIN_FEE_PCT_TIER_1 = 0.05
ADMIN_FEE_PCT_TIER_2 = 0.04
ADMIN_FEE_PCT_TIER_3 = 0.03
ADMIN_FEE_TIER_1_MAX_CENTS = 5_000_000
ADMIN_FEE_TIER_2_MAX_CENTS = 20_000_000

# ─── Policy defaults (PRD §3.1) ────────────────────────────────────────────
DEFAULT_MIN_PASSING_GRADE_POINTS = 2.00
DEFAULT_NON_CATALOG_APPROVAL_REQUIRED = True

# ─── Partner agreement / listing (PRD §2.5, §3.2) ──────────────────────────
MAX_NEGOTIATED_DISCOUNT_PCT = 0.60

# ─── Direct billing (PRD §3.5) ─────────────────────────────────────────────
# "its due_date is the term_start_date advanced by 30 days".
INVOICE_DUE_DAYS = 30

# ─── Approval request revision cycle (PRD §3.3) ────────────────────────────
MAX_REVISION_ROUNDS = 2

# ─── Persistence risk score (PRD §3.8) ─────────────────────────────────────
BASE_RISK_BY_CREDENTIAL = {
    "CERTIFICATE": 10,
    "ASSOCIATE": 20,
    "BACHELOR": 30,
    "MASTER": 25,
}
OUTCOME_PENALTY = 30
STALENESS_PENALTY = 20
COACH_STALE_DAYS = 45
ENGAGEMENT_PER_SESSION = 5
ENGAGEMENT_CAP = 20
FLAG_WEIGHT = 5
FLAG_COUNT_CAP = 4
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100
PERSISTENCE_TIER_MEDIUM_FLOOR = 30
PERSISTENCE_TIER_HIGH_FLOOR = 60

# ─── Utilization report (PRD §2.5) ─────────────────────────────────────────
UTILIZATION_RATE_DECIMAL_PLACES = 4


def round_half_up(value) -> int:
    """Round a numeric value half up to a whole cent, as PRD §2.5 mandates."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_rate_half_up(value, places: int = UTILIZATION_RATE_DECIMAL_PLACES) -> float:
    """Round a ratio half up to `places` decimal places (PRD §2.5)."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def expected_admin_fee_pct(pre_settlement_disbursed_cents: int) -> float:
    """Select the platform fee percentage from the pre-settlement fee basis."""
    if pre_settlement_disbursed_cents < ADMIN_FEE_TIER_1_MAX_CENTS:
        return ADMIN_FEE_PCT_TIER_1
    if pre_settlement_disbursed_cents < ADMIN_FEE_TIER_2_MAX_CENTS:
        return ADMIN_FEE_PCT_TIER_2
    return ADMIN_FEE_PCT_TIER_3


def expected_persistence_tier(score: int) -> str:
    """Band a persistence risk score into its tier (PRD §3.8)."""
    if score < PERSISTENCE_TIER_MEDIUM_FLOOR:
        return "LOW"
    if score < PERSISTENCE_TIER_HIGH_FLOOR:
        return "MEDIUM"
    return "HIGH"
