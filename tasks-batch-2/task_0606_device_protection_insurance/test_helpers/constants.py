"""Domain thresholds — numeric constants from PRD calculations."""

# quote_deductible
RISK_SURCHARGE_BPS = 2500          # WATCH surcharge = 25% of tier base

# replacement_value
MIN_RESIDUAL_FLOOR_CENTS = 5000    # depreciated value floor
DAYS_PER_MONTH = 30

# fraud_velocity
VELOCITY_WINDOW_DAYS = 90
REVIEW_THRESHOLD = 2               # outcome REVIEW at >= 2
BLOCK_THRESHOLD = 3               # outcome BLOCK at >= 3

# tradein_credit grade factors (basis points)
GRADE_A_BPS = 6000
GRADE_B_BPS = 4000
GRADE_C_BPS = 2000
GRADE_EWASTE_BPS = 0

# nonreturn_fee
NONRETURN_FEE_BPS = 3500          # 35% of MSRP

# advanced exchange ship return window
RETURN_WINDOW_DAYS = 30

# Shared fixture conventions used across the design indices.
PLAN_STD = {
    "code": "PLAN_STD",
    "monthly_premium_cents": 2000,
    "base_deductible_cents": 10000,
    "loss_deductible_multiplier_bps": 15000,
    "annual_claim_limit": 2,
    "replacement_value_cap_cents": 80000,
}

SKU_BOOK = {
    "model_name": "BOOK",
    "msrp_cents": 90000,
    "depreciation_rate_bps_per_month": 200,
    "stock_on_hand": 5,
}

SKU_CAPPED = {
    "model_name": "CAPPED",
    "msrp_cents": 200000,
    "depreciation_rate_bps_per_month": 100,
    "stock_on_hand": 5,
}

# 15-digit, Luhn-valid IMEIs and one that fails Luhn.
IMEI_A = "356758901234560"
IMEI_B = "490154203237518"
IMEI_BAD = "356758901234561"

CLOCK_DEFAULT = "2026-06-01T00:00:00Z"
PURCHASE_DATE = "2025-12-01T00:00:00Z"
# Activation instant: enrolled_at must precede every incident_at the suite files
# (earliest is 2026-03-10) so claims fall strictly after activation and at/before
# the 2026-06-01 clock. Activation is bracketed at this early instant, then the
# clock is restored to CLOCK_DEFAULT for claim filing.
ENROLL_CLOCK = "2026-01-15T00:00:00Z"
