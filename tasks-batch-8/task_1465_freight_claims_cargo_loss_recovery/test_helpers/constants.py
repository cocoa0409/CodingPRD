"""Domain thresholds and numeric constants from the PRD calculations."""

# Settlement authority (PRD: settlement authority tiering)
TIER_2_CAP_CENTS = 10_000_000  # amounts above this require FinanceController authority

# Reserve sizing guidance (PRD: reserve sizing)
LANE_ALERT_THRESHOLD_BP = 1500     # carrier claim-ratio portfolio alert threshold
MAX_RESERVE_MULTIPLE = 2           # suggestion capped at 2x computed liability
MULT_HIGH_VALUE = 1.20             # HIGH_VALUE commodity multiplier
MULT_CONCEALED = 1.10              # concealed-damage multiplier
MULT_CARRIER_ALERT = 1.15          # carrier ratio above alert threshold
MULT_LANE_ABOVE_BASELINE = 1.05    # lane ratio above its baseline

# Claim-ratio analytics (PRD: claim-ratio analytics)
BASIS_POINT_DENOMINATOR = 10_000

# Aging buckets (PRD: portfolio aging), in whole days
BUCKET_B0_30_MAX_DAYS = 30
BUCKET_B31_60_MAX_DAYS = 60
BUCKET_B61_90_MAX_DAYS = 90

# Scheduled transitions (PRD: logical clock and scheduled transitions)
SETTLEMENT_EXPIRY_DAYS = 14
ACK_TIME_BAR_EXTRA_DAYS = 365

# Carmack defaults applied at carrier registration
DEFAULT_CARMACK_ACKNOWLEDGMENT_DAYS = 30
DEFAULT_CARMACK_FILING_DAYS = 270

# Logical clock default before any PlatformAdmin call
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "DECLARED_VALUE_CENTS": 50_000,
    "CLAIMED_AMOUNT_CENTS": 40_000,
    "TOTAL_WEIGHT_LBS": 50,
    "PACKAGE_COUNT": 5,
    "MAX_AUTO_SETTLE_CENTS": 100_000,
    "BASELINE_CLAIM_RATIO_BP": 900,
    "SETUP_CLOCK": "2026-06-01T00:00:00Z",
    "SUBMIT_CLOCK": "2026-06-10T00:00:00Z",
    "SHIP_DATE": "2026-06-01T00:00:00Z",
    "DELIVERY_DATE": "2026-06-05T00:00:00Z",
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-01-01T00:00:00Z",
}
