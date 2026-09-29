"""Domain thresholds and rates stated in the PRD narratives."""

# Cabin weights used by the coupon-level revenue allocation (PRD 3.5).
CLASS_WEIGHT_BP = {
    "ECONOMY": 10000,
    "PREMIUM": 12500,
    "BUSINESS": 16000,
    "FIRST": 20000,
}

# Frequent-flyer earning multipliers stamped at fly time (PRD 3.4).
FFP_MULTIPLIER_BP = {
    "ECONOMY": 5000,
    "PREMIUM": 10000,
    "BUSINESS": 15000,
    "FIRST": 20000,
}

# Mileage cost tiers, per thousand miles (PRD 3.4 / 3.7).
FFP_TIERS = {
    "TIER_A_CEILING_MILES": 10000,
    "TIER_B_CEILING_MILES": 40000,
    "TIER_A_RATE_PER_1000": 1400,
    "TIER_B_RATE_PER_1000": 1150,
    "TIER_C_RATE_PER_1000": 900,
}

# Clearing-house handling-fee scale, keyed on the pre-fee gross (PRD 3.6).
FEE_TIERS = {
    "TIER_1_CEILING": 500000,
    "TIER_2_CEILING": 5000000,
    "BP_TIER_1": 75,
    "BP_TIER_2": 50,
    "BP_TIER_3": 25,
}

LATE_PENALTY_BP = 200

# Undercharge extrapolation (PRD 3.9).
AUDIT = {
    "MATERIALITY_BP": 200,
    "COVERAGE_TIER_HIGH_BP": 2000,
    "COVERAGE_TIER_MID_BP": 500,
    "HAIRCUT_HIGH_BP": 0,
    "HAIRCUT_MID_BP": 1500,
    "HAIRCUT_LOW_BP": 3500,
    "CAP_MULTIPLE": 25,
    "TIME_BAR_DAYS": 730,
}

# Memo aging and negotiation limits (PRD 3.8).
MEMO = {
    "BUCKET_1_DAYS": 30,
    "BUCKET_2_DAYS": 60,
    "BUCKET_3_DAYS": 90,
    "ARBITRATION_MIN_AGE_DAYS": 90,
    "RAISE_WINDOW_DAYS": 45,
    "MAX_STAGE": 3,
}

# Straight-rate default weight multiplier and the FX rate scale (PRD 3.2 / 2.6).
DEFAULT_FACTOR_BP = 10000
RATE_SCALE = 1000000

# Reproration count at which a validating carrier's audit_flag is set (PRD 3.8).
AUDIT_FLAG_REPRORATION_THRESHOLD = 3

# Convenience values used by the composite fixtures.
TEST_DEFAULTS = {
    "BIG_CREDIT_LIMIT": 100000000,
    "DEFAULT_FARE_MINOR": 100000,
    "DEFAULT_TPM_MILES": 1000,
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
    "CLOCK_TRADING_DAY": "2026-08-10T00:00:00Z",
    "CLOCK_FIXING_DAY": "2026-09-06T00:00:00Z",
    "PERIOD_CODE": "2026-08-P1",
    "PERIOD_START": "2026-08-01T00:00:00Z",
    "PERIOD_END": "2026-09-01T00:00:00Z",
    "SUBMISSION_DEADLINE": "2026-09-05T00:00:00Z",
    "RATE_FIXING_DATE": "2026-09-06T00:00:00Z",
}

# A well-formed UUID that never resolves to a stored row.
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_UUIDS = {
    "agreement": "11111111-1111-4111-8111-111111111111",
    "period": "22222222-2222-4222-8222-222222222222",
    "invoice": "33333333-3333-4333-8333-333333333333",
    "coupon": "44444444-4444-4444-8444-444444444444",
    "memo": "55555555-5555-4555-8555-555555555555",
    "sample": "66666666-6666-4666-8666-666666666666",
    "carrier": "77777777-7777-4777-8777-777777777777",
    "spare": "88888888-8888-4888-8888-888888888888",
}
