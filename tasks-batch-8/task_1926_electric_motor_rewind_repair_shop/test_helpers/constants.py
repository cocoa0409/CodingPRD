"""Domain thresholds and numeric constants named in the PRD (§2.4, §3.2–§3.7)."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Canonical shop configuration used across test setups.
CANONICAL_SHOP = {
    "shop_name": "S",
    "easa_accreditation_id": "EASA-12345",
    "labor_rate_small_cents": 8500,
    "labor_rate_medium_cents": 9500,
    "labor_rate_large_cents": 11200,
    "labor_rate_xlarge_cents": 13800,
    "rush_premium_pct": 0.35,
    "replace_threshold_pct": 0.65,
    "supplies_low_pct": 0.08,
    "supplies_high_pct": 0.06,
    "warranty_months": 12,
    "pool_slot_monthly_cents": 4500,
    "pool_loan_daily_cents": 1800,
    "pool_loan_grace_days": 3,
}

# Labor-rate frame tiers in mm (PRD §3.3).
TIER_SMALL_MAX_MM = 200
TIER_MEDIUM_MAX_MM = 355
TIER_LARGE_MAX_MM = 560

# Shop-supplies marginal tier break, in cents (PRD §3.3: $1,000.00).
SUPPLIES_TIER_BREAK_CENTS = 100_000

# Rush/emergency pricing (PRD §3.3).
EMERGENCY_MULTIPLIER = 1.5

# Quote validity window in days (PRD §3.3).
QUOTE_VALID_DAYS = 30

# Failure-risk tiers (PRD §3.3).
RISK_CORE_LOSS_FAIL = 0.35
RISK_AGE_15 = 0.25
RISK_AGE_8 = 0.15
RISK_BASE = 0.08
RISK_AGE_15_YEARS = 15
RISK_AGE_8_YEARS = 8

# Core-loss verdict threshold (PRD §3.2): pass at or below 5% of rated watts.
CORE_LOSS_MAX_PCT = 0.05

# Vibration limits in mm/s by frame tier (PRD §3.4).
VIB_LIMIT_SMALL = 2.8
VIB_LIMIT_MEDIUM = 3.5
VIB_LIMIT_LARGE = 4.5
VIB_FRAME_SMALL_MAX_MM = 315
VIB_FRAME_MEDIUM_MAX_MM = 630

# Invoice line-item fees in cents (PRD §3.5).
INCOMING_TEST_FEE_CENTS = 7500
CORE_LOSS_TEST_FEE_CENTS = 12000
BALANCING_FEE_CENTS = 9500
FINAL_TEST_FEE_CENTS = 8500

# Invoice net terms in days (PRD §3.5).
NET30_DAYS = 30

# Customer standing: HOLD requires strictly more than this many days past due
# (PRD §3.5).
STANDING_HOLD_DAYS = 30

# Pool spare kW band: +/-20% inclusive of the unit under repair (PRD §3.6).
POOL_KW_BAND_PCT = 0.20
