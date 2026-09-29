"""Numeric constants the PRD declares, plus the canonical seed values tests reuse.

``THRESHOLDS`` holds figures the PRD fixes contractually (rate ladders, tier bounds,
caps and ceilings). ``TEST_DEFAULTS`` holds the seed payload values shared by the
fixtures so that a single canonical lease stream produces the same derived numbers
everywhere.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401  (re-exported)

# A syntactically valid uuid that no record in a freshly started server can own.
UNKNOWN_UUID = "3f7c1a52-9b64-4d18-8e2a-6c5f0b91d4e7"
UNKNOWN_UUID_ALT = "8a2d4e60-1c39-4f75-9b8e-2d7a5c60f3b1"

THRESHOLDS = {
    # --- Logical clock (PRD section 2.6) ---
    "CLOCK_DEFAULT_UTC": "2026-08-01T00:00:00Z",
    "MORTGAGEE_CONSENT_WINDOW_DAYS": 21,
    "CURE_DEADLINE_DAYS": 30,
    # --- Pagination (PRD section 2.3) ---
    "LIMIT_DEFAULT": 20,
    "LIMIT_MIN": 1,
    "LIMIT_MAX": 100,
    "OFFSET_DEFAULT": 0,
    # --- Portfolio capital posture ladder (PRD section 3.1) ---
    "POSTURE_FROZEN_UTILIZATION_BPS": 9000,
    "POSTURE_CONSTRAINED_UTILIZATION_BPS": 7500,
    # --- Tenancy quality score (PRD section 3.3) ---
    "CREDIT_POINTS_INVESTMENT_GRADE": 40,
    "CREDIT_POINTS_CROSSOVER": 25,
    "CREDIT_POINTS_SPECULATIVE": 10,
    "TENANCY_WEIGHT_ANCHOR": "1.0",
    "TENANCY_WEIGHT_COLOCATION": "0.6",
    "HOLDOVER_PENALTY_POINTS": 5,
    "STREAM_SCORE_MIN": 0,
    "STREAM_SCORE_MAX": 100,
    # --- Discount rate ladder keyed on tenancy quality score (PRD section 3.4) ---
    "DISCOUNT_BPS_SCORE_80_PLUS": 700,
    "DISCOUNT_BPS_SCORE_60_PLUS": 850,
    "DISCOUNT_BPS_SCORE_40_PLUS": 1000,
    "DISCOUNT_BPS_SCORE_BELOW_40": 1250,
    # --- Valuation mechanics (PRD section 3.4) ---
    "LUMP_SUM_HORIZON_YEARS": 40,
    "RENEWAL_HAIRCUT_BPS": 2000,
    "CPI_CAPPED_GROWTH_CEILING_BPS": 250,
    "PREPAID_DISCOUNT_PREMIUM_BPS": 150,
    "PREPAID_TERM_HAIRCUT_BPS": 500,
    "MAX_BID_MULTIPLIER_BPS": 10500,
    # --- Negotiation and cure ceilings (PRD sections 3.5 and 3.8) ---
    "NEGOTIATION_ROUND_CAP": 3,
    "CURE_ATTEMPT_CAP": 3,
    # --- Settlement (PRD section 3.7) ---
    "BROKER_TIER_HIGH_GROSS_CENTS": 30_000_000,
    "BROKER_TIER_MID_GROSS_CENTS": 10_000_000,
    "BROKER_FEE_BPS_HIGH": 150,
    "BROKER_FEE_BPS_MID": 200,
    "BROKER_FEE_BPS_LOW": 250,
    "HOLDBACK_BPS_PER_DISPUTE": 250,
    "HOLDBACK_BPS_CAP": 1000,
    # --- Revenue share (PRD section 3.8) ---
    "AMENDMENT_PASS_THROUGH_CAP_BPS": 2000,
    # --- Collateral haircuts keyed on servicing status (PRD section 3.9) ---
    "HAIRCUT_BPS_PERFORMING": 0,
    "HAIRCUT_BPS_WATCHLIST": 3000,
    "HAIRCUT_BPS_DELINQUENT": 5000,
    "HAIRCUT_BPS_IMPAIRED": 10000,
}

TEST_DEFAULTS = {
    # Portfolio
    "PORTFOLIO_NAME": "Northeast Tower Aggregation",
    "PORTFOLIO_PROGRAM_CODE": "NE-AGG-01",
    "PORTFOLIO_CAPITAL_CENTS": 50_000_000,
    # Tower company and site
    "TOWER_COMPANY_NAME": "Summit Towers LLC",
    "TOWER_COMPANY_EMAIL": "rofr@summit.example",
    "ROFR_WINDOW_DAYS": 30,
    "SITE_CODE": "NE-1042",
    "STATE_CODE": "NY",
    "GROUND_AREA_SQFT": 2500,
    # Landowner
    "LANDOWNER_NAME": "Hollis Farm LLC",
    "LANDOWNER_EMAIL": "owner@hollis.example",
    # Lease stream
    "CURRENT_ANNUAL_RENT_CENTS": 3_600_000,
    "ESCALATOR_PCT_BPS": 300,
    "REMAINING_TERM_MONTHS": 180,
    # Anchor tenancy
    "ANCHOR_CARRIER_NAME": "Vantage Wireless",
    "ANCHOR_MONTHLY_RENT_SHARE_CENTS": 250_000,
    "TENANCY_TERM_END_DATE": "2034-06-30",
    # Deal and offer
    "REVENUE_SHARE_BPS": 2500,
    "OFFER_AMOUNT_CENTS": 36_000_000,
    "OFFER_EXPIRES_AT": "2026-12-31T00:00:00Z",
    "RECORDING_REF": "BK1420-PG318",
    # Facility and pledge
    "FACILITY_NAME": "Warehouse A",
    "ADVANCE_RATE_BPS": 6500,
    "CONCENTRATION_LIMIT_BPS_WIDE_OPEN": 10000,
    "PLEDGE_START_DATE": "2026-08-01",
    "PLEDGE_END_DATE": "2026-12-31",
}

# Derived figures the PRD's own formulas produce from the canonical seed above. They are
# recorded here only so several fixtures can agree on the same expected ledger.
CANONICAL = {
    "STREAM_SCORE": 40,
    "DISCOUNT_BPS": 1000,
    "LUMP_SUM_VALUE_CENTS": 44_627_011,
    "MAX_BID_CENTS": 46_858_362,
    "BROKER_FEE_CENTS": 540_000,
    "TOTAL_COMMITMENT_CENTS": 36_540_000,
    "NET_PROCEEDS_CENTS": 36_000_000,
}

__all__ = ["THRESHOLDS", "TEST_DEFAULTS", "CANONICAL", "UNKNOWN_UUID", "UNKNOWN_UUID_ALT", "NON_EXISTENT_UUID"]
