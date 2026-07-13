"""Domain thresholds and reusable numeric test defaults drawn from the PRD's calculations."""

# PRD §3.9 — invoice fee/retainage arithmetic.
BILLING_THRESHOLD_PCT = 50
RETAINAGE_TIER_1_BP = 1000   # ratio <= 5000 bp
RETAINAGE_TIER_2_BP = 500    # 5000 bp < ratio <= 9000 bp
RETAINAGE_TIER_3_BP = 0      # ratio > 9000 bp
RETAINAGE_TIER_1_MAX_RATIO_BP = 5000
RETAINAGE_TIER_2_MAX_RATIO_BP = 9000

# PRD §3.4 — the RFI clarification loop is bounded at two rounds.
MAX_CLARIFICATION_ROUNDS = 2

# PRD §3.2 — the four phases' weight_bp must sum to exactly this at execution.
TOTAL_WEIGHT_BP = 10_000

# PRD §3.2 / §3.3 — the four design phases in ascending phase_order.
PHASE_CODES = ("SD", "DD", "CD", "CA")
PHASE_ORDER = {"SD": 1, "DD": 2, "CD": 3, "CA": 4}

# PRD §3.2 — submittal_review_period_days defaults to 14 when omitted.
DEFAULT_SUBMITTAL_REVIEW_PERIOD_DAYS = 14

# PRD §3.4 — markup_bp defaults to 1000 basis points (ten percent).
DEFAULT_MARKUP_BP = 1000
MAX_MARKUP_BP = 5000

# PRD §2.4 — the logical clock reads this before it has ever been set.
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# PRD §2.3 — pagination bounds.
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# Reusable test values.
TEST_DEFAULTS = {
    "PRINCIPAL_A": "principal-alice",
    "PRINCIPAL_B": "principal-bob",
    "CLIENT_REP": "client-1",
    "OTHER_CLIENT_REP": "client-9",
    "CONSTRUCTION_COST_CENTS": 100_000_000,
    "FEE_RATE_BP": 1000,          # -> base_fee_cents 10_000_000
    "BASE_FEE_CENTS": 10_000_000,
    "LABOR_BUDGET_CENTS": 10_000_000,
    "PM_BILLING_RATE": 25_000,
    "PM_COST_RATE": 12_000,
    "ARCH_BILLING_RATE": 12_000,
    "ARCH_COST_RATE": 5_000,
}

# Balanced weights whose fee allocation is exact at base_fee_cents 10_000_000:
# SD 2_000_000 / DD 2_000_000 / CD 4_000_000 / CA 2_000_000.
STANDARD_WEIGHTS = (2000, 2000, 4000, 2000)
