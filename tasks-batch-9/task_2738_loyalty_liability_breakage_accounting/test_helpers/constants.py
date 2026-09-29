"""
Domain vocabulary and reusable configuration for the Loyalty Liability &
Breakage Accounting API.

Everything here is taken from the contract: role names, enum values, the logical
clock's startup instant, and the one programme configuration that most tests
build on. Money is always an integer number of cents, a rate or multiplier is
always basis points (10000 bp == 1.0000), and a stand-alone selling price is
always millicents per point (thousandths of a cent).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict

# ─── Roles ───────────────────────────────────────────────────────────────────
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_LOYALTY_ACCOUNTANT = "LoyaltyAccountant"
ROLE_CONTROLLER = "Controller"
ROLE_PARTNER_OPERATOR = "PartnerOperator"
ROLE_MEMBER = "Member"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_LOYALTY_ACCOUNTANT,
    ROLE_CONTROLLER,
    ROLE_PARTNER_OPERATOR,
    ROLE_MEMBER,
)

# ─── Logical clock ───────────────────────────────────────────────────────────
# The server's startup default; every test sets it explicitly anyway.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ─── LoyaltyProgram ──────────────────────────────────────────────────────────
PROGRAM_DRAFT = "DRAFT"
PROGRAM_ACTIVE = "ACTIVE"
PROGRAM_SUSPENDED = "SUSPENDED"
PROGRAM_CLOSED = "CLOSED"

BREAKAGE_METHOD_COHORT_WEIGHTED = "COHORT_WEIGHTED"
BREAKAGE_METHOD_PROGRAM_HISTORICAL = "PROGRAM_HISTORICAL"

CURRENCY_USD = "USD"

TIER_BASE = "BASE"
TIER_SILVER = "SILVER"
TIER_GOLD = "GOLD"
TIER_PLATINUM = "PLATINUM"

# The four-key multiplier map every programme must declare, exactly.
TIER_MULTIPLIER_BP: Dict[str, int] = {
    TIER_BASE: 10000,
    TIER_SILVER: 10300,
    TIER_GOLD: 12500,
    TIER_PLATINUM: 15000,
}

# The reference programme configuration.
DEFAULT_SSP_MILLICENTS_PER_POINT = 1200
DEFAULT_POINT_EXPIRY_DAYS = 730
DEFAULT_PER_ISSUANCE_POINT_CAP = 5000
DEFAULT_PROMO_MULTIPLIER_CAP_BP = 30000
DEFAULT_HISTORICAL_REDEMPTION_RATE_BP = 7500
DEFAULT_ESCHEAT_DISCLOSURE_THRESHOLD_CENTS = 100000
# 10000 - 7500, the rate the first activation seeds.
DEFAULT_SEEDED_BREAKAGE_RATE_BP = 2500

IDENTITY_MULTIPLIER_BP = 10000

# ─── AccountingPeriod ────────────────────────────────────────────────────────
PERIOD_OPEN = "OPEN"
PERIOD_SOFT_CLOSED = "SOFT_CLOSED"
PERIOD_HARD_CLOSED = "HARD_CLOSED"

PERIOD_AUG_CODE = "2026-08"
PERIOD_AUG_START = "2026-08-01T00:00:00Z"
PERIOD_AUG_END = "2026-09-01T00:00:00Z"
PERIOD_SEP_CODE = "2026-09"
PERIOD_SEP_START = "2026-09-01T00:00:00Z"
PERIOD_SEP_END = "2026-10-01T00:00:00Z"

# The eight rollforward figures plus the pinned rate, all reset by a reopen.
CLOSE_DERIVED_FIELDS = (
    "opening_liability_cents",
    "pre_catchup_liability_cents",
    "required_liability_cents",
    "catch_up_adjustment_cents",
    "closing_liability_cents",
    "breakage_recognized_cents",
    "approved_estimate_rate_bp",
)

# The four movement accumulators a reopen must leave alone.
MOVEMENT_ACCUMULATOR_FIELDS = (
    "issuance_deferred_cents",
    "redemption_recognized_cents",
    "remeasurement_delta_cents",
    "expiry_released_cents",
)

# ─── Cohort ──────────────────────────────────────────────────────────────────
COHORT_C1_CODE = "C1"
COHORT_C1_ENROLLMENT_START = "2024-01-01T00:00:00Z"
COHORT_C1_ENROLLMENT_END = "2024-12-31T00:00:00Z"
COHORT_C1_OBSERVED_RATE_BP = 8200
COHORT_C1_SAMPLE_SIZE = 40000

COHORT_C2_CODE = "C2"
COHORT_C2_ENROLLMENT_START = "2025-01-01T00:00:00Z"
COHORT_C2_ENROLLMENT_END = "2025-12-31T00:00:00Z"
COHORT_C2_OBSERVED_RATE_BP = 400
COHORT_C2_SAMPLE_SIZE = 9000
COHORT_C2_ADJUSTMENT_BP = -300

# The clamp the cohort-weighted calculation applies to each cohort in turn.
REDEMPTION_RATE_FLOOR_BP = 200
REDEMPTION_RATE_CEILING_BP = 9800

# The clamp applied to a cohort's program_change_adjustment_bp.
COHORT_ADJUSTMENT_FLOOR_BP = -5000
COHORT_ADJUSTMENT_CEILING_BP = 5000

# The values a cohort takes when the create request omits them.
DEFAULT_SAMPLE_SIZE = 5000
DEFAULT_PROGRAM_CHANGE_ADJUSTMENT_BP = 0

# ─── Member ──────────────────────────────────────────────────────────────────
MEMBER_ACTIVE = "ACTIVE"
MEMBER_DORMANT = "DORMANT"
MEMBER_CLOSED = "CLOSED"

DORMANCY_THRESHOLD_DAYS = 730

STATE_TX = "TX"
STATE_DE = "DE"

# ─── StateExpiryRule ─────────────────────────────────────────────────────────
DEFAULT_MIN_DORMANCY_DAYS = 730

# ─── PartnerAgreement ────────────────────────────────────────────────────────
AGREEMENT_ACTIVE = "ACTIVE"
AGREEMENT_SUSPENDED = "SUSPENDED"
AGREEMENT_TERMINATED = "TERMINATED"

RELATIONSHIP_THIRD_PARTY = "THIRD_PARTY"
RELATIONSHIP_INTERCOMPANY = "INTERCOMPANY"

PARTNER_PG_CODE = "PG"
PARTNER_PN_CODE = "PN"
DEFAULT_ISSUANCE_RATE_MILLICENTS = 900
DEFAULT_REDEMPTION_RATE_MILLICENTS = 1100
PARTNER_WINDOW_START = "2026-08-01T00:00:00Z"
PARTNER_WINDOW_END = "2026-12-31T00:00:00Z"

# The values an agreement takes when the create request omits them.
DEFAULT_SETTLEMENT_LAG_DAYS = 30
DEFAULT_NET_SETTLEMENT_ENABLED = False
DEFAULT_MIN_INVOICE_CENTS = 5000

# ─── PointLot ────────────────────────────────────────────────────────────────
LOT_OUTSTANDING = "OUTSTANDING"
LOT_PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
LOT_FULLY_REDEEMED = "FULLY_REDEEMED"
LOT_EXPIRED = "EXPIRED"
LOT_ESCHEATED = "ESCHEATED"

SETTLEMENT_NOT_APPLICABLE = "NOT_APPLICABLE"
SETTLEMENT_PENDING = "PENDING_SETTLEMENT"
SETTLEMENT_SETTLED = "SETTLED"
SETTLEMENT_WRITTEN_OFF = "WRITTEN_OFF"

# ─── RedemptionEvent ─────────────────────────────────────────────────────────
REDEMPTION_REQUESTED = "REQUESTED"
REDEMPTION_ALLOCATED = "ALLOCATED"
REDEMPTION_FULFILLED = "FULFILLED"
REDEMPTION_REVERSED = "REVERSED"

REDEMPTION_TYPE_CATALOG = "CATALOG"
REDEMPTION_TYPE_PARTNER = "PARTNER"
REDEMPTION_TYPE_CASH_BACK = "CASH_BACK"

ENTRY_TYPE_ALLOCATION = "ALLOCATION"
ENTRY_TYPE_REVERSAL = "REVERSAL"

# ─── BreakageEstimate ────────────────────────────────────────────────────────
ESTIMATE_DRAFT = "DRAFT"
ESTIMATE_SUBMITTED = "SUBMITTED"
ESTIMATE_APPROVED = "APPROVED"
ESTIMATE_REJECTED = "REJECTED"
ESTIMATE_SUPERSEDED = "SUPERSEDED"

METHOD_COHORT_WEIGHTED = "COHORT_WEIGHTED"
METHOD_SINGLE_COHORT = "SINGLE_COHORT"
METHOD_PROGRAM_HISTORICAL = "PROGRAM_HISTORICAL"

# ─── SettlementStatement ─────────────────────────────────────────────────────
STATEMENT_DRAFT = "DRAFT"
STATEMENT_ISSUED = "ISSUED"
STATEMENT_DISPUTED = "DISPUTED"
STATEMENT_PAID = "PAID"
STATEMENT_WRITTEN_OFF = "WRITTEN_OFF"
STATEMENT_SUPERSEDED = "SUPERSEDED"

BASIS_GROSS = "GROSS"
BASIS_NET = "NET"

# ─── ProgramChangeOrder ──────────────────────────────────────────────────────
ORDER_MODELED = "MODELED"
ORDER_APPROVED = "APPROVED"
# Applying an approved order drives it to the terminal EFFECTIVE state.
ORDER_EFFECTIVE = "EFFECTIVE"
ORDER_CANCELLED = "CANCELLED"

CHANGE_EXPIRY_DAYS = "EXPIRY_DAYS_CHANGE"
CHANGE_SSP = "SSP_CHANGE"
CHANGE_TIER_MULTIPLIER = "TIER_MULTIPLIER_CHANGE"

# ─── Bounded cycles ──────────────────────────────────────────────────────────
# Each counter is budgeted at two and is never reset.
CYCLE_BUDGET = 2

# ─── Pagination ──────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MAX_LIMIT = 100

# ─── Probes ──────────────────────────────────────────────────────────────────
# An identifier no chain ever mints, for the not-found band.
UNKNOWN_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


# ─── Rounding ────────────────────────────────────────────────────────────────
def round_half_up(numerator: int, denominator: int) -> int:
    """
    Divide and round half away from zero, the single rounding mode the contract
    uses for every money and point figure.
    """
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def points_to_cents(points: int, ssp_millicents_per_point: int) -> int:
    """Convert a point count at a stand-alone selling price into whole cents."""
    return round_half_up(points * ssp_millicents_per_point, 1000)


def apply_bp(cents: int, rate_bp: int) -> int:
    """Apply a basis-point rate to a cent amount, rounded half up."""
    return round_half_up(cents * rate_bp, 10000)


def clamp(value: int, low: int, high: int) -> int:
    """Clamp an integer into an inclusive band."""
    return max(low, min(high, value))


# ─── Convenience: the reference programme payload body ───────────────────────
def default_program_config(**overrides: Any) -> Dict[str, Any]:
    """The reference programme configuration as a plain dict."""
    config: Dict[str, Any] = {
        "currency_code": CURRENCY_USD,
        "ssp_millicents_per_point": DEFAULT_SSP_MILLICENTS_PER_POINT,
        "point_expiry_days": DEFAULT_POINT_EXPIRY_DAYS,
        "per_issuance_point_cap": DEFAULT_PER_ISSUANCE_POINT_CAP,
        "tier_multiplier_bp": dict(TIER_MULTIPLIER_BP),
        "promo_multiplier_cap_bp": DEFAULT_PROMO_MULTIPLIER_CAP_BP,
        "breakage_method": BREAKAGE_METHOD_COHORT_WEIGHTED,
        "historical_redemption_rate_bp": DEFAULT_HISTORICAL_REDEMPTION_RATE_BP,
        "escheat_disclosure_threshold_cents": DEFAULT_ESCHEAT_DISCLOSURE_THRESHOLD_CENTS,
    }
    config.update(overrides)
    return config
