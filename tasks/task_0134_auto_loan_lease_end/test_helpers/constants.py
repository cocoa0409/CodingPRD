"""Domain thresholds — numeric constants traceable to verbatim PRD prose.

Each constant cites the PRD sentence that names it.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# FICO score range and tier boundaries — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "validates that fico_score lies between 300 and 850 inclusive;
# values outside that range are rejected with ERR_FICO_OUT_OF_RANGE."
FICO_MIN: int = 300
FICO_MAX: int = 850

# PRD §3.1: "a score of at least 720 maps to TIER_1; a score below 720 but
# at least 660 maps to TIER_2; a score below 660 but at least 600 maps to
# TIER_3; a score below 600 but at least 540 maps to TIER_4; any score
# below 540 maps to TIER_5_DECLINED."
TIER_1_MIN_FICO: int = 720
TIER_2_MIN_FICO: int = 660
TIER_3_MIN_FICO: int = 600
TIER_4_MIN_FICO: int = 540


# ---------------------------------------------------------------------------
# Vehicle constraints — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "residual_factor_bps ... constrained to lie between 1000 and
# 8000 inclusive (so 5500 represents a 55% residual)".
RESIDUAL_FACTOR_BPS_MIN: int = 1000
RESIDUAL_FACTOR_BPS_MAX: int = 8000

VIN_LENGTH: int = 17  # PRD §3.2: "17-character vehicle identification number"


# ---------------------------------------------------------------------------
# Loan tier APR (basis points) — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "TIER_1 carries an APR of 450 basis points (4.50%), TIER_2
# carries 650 (6.50%), TIER_3 carries 950 (9.50%), and TIER_4 carries 1450
# (14.50%)."
TIER_1_APR_BPS: int = 450
TIER_2_APR_BPS: int = 650
TIER_3_APR_BPS: int = 950
TIER_4_APR_BPS: int = 1450


# ---------------------------------------------------------------------------
# Loan minimum down payment (basis points of msrp_cents) — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "For TIER_1 it is 5% (500 basis points), for TIER_2 it is 10%
# (1000 basis points), for TIER_3 it is 20% (2000 basis points), and for
# TIER_4 it is 35% (3500 basis points)."
TIER_1_DP_BPS_LOAN: int = 500
TIER_2_DP_BPS_LOAN: int = 1000
TIER_3_DP_BPS_LOAN: int = 2000
TIER_4_DP_BPS_LOAN: int = 3500


# ---------------------------------------------------------------------------
# Allowed loan/lease terms — PRD §3.3 and §3.4
# ---------------------------------------------------------------------------
# PRD §3.3: "term_months value must be one of the four supported terms —
# 36, 48, 60, or 72 months — and a request that names any other value is
# rejected with ERR_INVALID_REQUEST."
LOAN_TERM_MONTHS_ALLOWED = (36, 48, 60, 72)
# PRD §3.4: "term_months for a lease must be one of 24, 36, or 48 months."
LEASE_TERM_MONTHS_ALLOWED = (24, 36, 48)


# ---------------------------------------------------------------------------
# Lease money factor by tier — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "TIER_1 carries 2000 (a money factor of 0.00200), TIER_2
# carries 2800 (0.00280), and TIER_3 carries 4000 (0.00400)".
TIER_1_MF_MICRO: int = 2000
TIER_2_MF_MICRO: int = 2800
TIER_3_MF_MICRO: int = 4000


# ---------------------------------------------------------------------------
# Lease minimum down payment (bps of msrp_cents) — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "TIER_1 requires 8% (800 basis points), TIER_2 requires 12%
# (1200 basis points), and TIER_3 requires 18% (1800 basis points)."
TIER_1_DP_BPS_LEASE: int = 800
TIER_2_DP_BPS_LEASE: int = 1200
TIER_3_DP_BPS_LEASE: int = 1800


# ---------------------------------------------------------------------------
# Lease tax — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "The tax cents is the ceiling of base cents multiplied by 800 —
# the local lease tax of 8%, expressed as basis points — divided by 10000."
LEASE_TAX_BPS: int = 800


# ---------------------------------------------------------------------------
# Lease mileage allowance bounds — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "constrained to lie between 10000 and 75000 inclusive (so a
# typical 36-month lease at 12k miles per year is 36000)."
MILEAGE_ALLOWANCE_MIN: int = 10000
MILEAGE_ALLOWANCE_MAX: int = 75000


# ---------------------------------------------------------------------------
# Mileage overage penalty — PRD §3.9
# ---------------------------------------------------------------------------
# PRD §3.9: "mileage_penalty_cents becomes mileage_overage multiplied by
# the per-mile penalty of 25 cents ($0.25 per mile)".
PENALTY_PER_MILE_CENTS: int = 25


# ---------------------------------------------------------------------------
# Disposition / purchase option fees — PRD §3.9
# ---------------------------------------------------------------------------
# PRD §3.9: "the assessment's purchase_option_cents is set to the lease's
# residual_value_cents plus the purchase option fee of 35000 cents ($350.00)".
PURCHASE_OPTION_FEE_CENTS: int = 35000
# PRD §3.9: "disposition_fee_cents is set to the disposition fee of 39500
# cents ($395.00)".
DISPOSITION_FEE_CENTS: int = 39500


# ---------------------------------------------------------------------------
# Default uplift — PRD §2.7 / §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "the uplift threshold of 3 lifetime defaults".
UPLIFT_THRESHOLD: int = 3
# PRD §3.5: "an APR uplift of 300 basis points (3.00%)".
APR_UPLIFT_BPS: int = 300
# PRD §3.5 / §2.10: defaults are sticky.

# ---------------------------------------------------------------------------
# Loan prepayment penalty — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "the ceiling of remaining_principal_cents multiplied by 200 —
# the prepayment penalty of 2.00% expressed as basis points — divided by
# 10000."
PREPAYMENT_PENALTY_BPS: int = 200


# ---------------------------------------------------------------------------
# Gap rider premium — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "the gap premium of 50 basis points (0.50% per month)".
GAP_PREMIUM_BPS: int = 50


# ---------------------------------------------------------------------------
# Clock advance bounds — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "The supplied days_advanced value must be between 1 and 365
# inclusive; an out-of-range value is rejected with
# ERR_CLOCK_ADVANCE_OUT_OF_RANGE."
CLOCK_ADVANCE_MIN: int = 1
CLOCK_ADVANCE_MAX: int = 365


# ---------------------------------------------------------------------------
# Days per period — PRD §3.3, §3.4
# ---------------------------------------------------------------------------
# PRD §3.3: "each row's due_day_index set to the loan's
# origination_day_index plus period_index multiplied by 30." Same for lease.
DAYS_PER_PERIOD: int = 30


# ---------------------------------------------------------------------------
# Default grace days — implementation detail referenced by §3.5 prose
# "grace-days threshold for default". Scaffold notes 15. We must NOT
# hard-code this in test assertions because the PRD prose does not state
# the integer; tests use behavioral assertions (LATE→DEFAULTED after a
# clock advance that brings the gap well past any reasonable grace).
# Provided here for fixture sizing only.
# ---------------------------------------------------------------------------
DEFAULT_GRACE_DAYS_BEHAVIORAL: int = 15


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit ... defaults to 10, with a minimum accepted value of 1
# and a maximum accepted value of 100."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test default values — convenient seed data for fixture builders. These
# are TEST conveniences, not PRD constants.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "FICO_TIER_1": 750,
    "FICO_TIER_2": 700,
    "FICO_TIER_3": 640,
    "FICO_TIER_4": 580,
    "FICO_TIER_5": 500,
    "MSRP_CENTS": 3_000_000,
    "RESIDUAL_FACTOR_BPS": 5500,
    "LOAN_DOWN_PAYMENT_CENTS": 150_000,
    "LOAN_TERM_MONTHS": 36,
    "LEASE_DOWN_PAYMENT_CENTS": 393_000,  # 393000 cents = $3930; > 8% of 3275000
    "LEASE_MSRP_CENTS": 3_275_000,
    "LEASE_RESIDUAL_FACTOR_BPS": 5800,
    "LEASE_TERM_MONTHS": 36,
    "MILEAGE_ALLOWANCE": 36_000,
}


__all__ = [
    "FICO_MIN",
    "FICO_MAX",
    "TIER_1_MIN_FICO",
    "TIER_2_MIN_FICO",
    "TIER_3_MIN_FICO",
    "TIER_4_MIN_FICO",
    "RESIDUAL_FACTOR_BPS_MIN",
    "RESIDUAL_FACTOR_BPS_MAX",
    "VIN_LENGTH",
    "TIER_1_APR_BPS",
    "TIER_2_APR_BPS",
    "TIER_3_APR_BPS",
    "TIER_4_APR_BPS",
    "TIER_1_DP_BPS_LOAN",
    "TIER_2_DP_BPS_LOAN",
    "TIER_3_DP_BPS_LOAN",
    "TIER_4_DP_BPS_LOAN",
    "LOAN_TERM_MONTHS_ALLOWED",
    "LEASE_TERM_MONTHS_ALLOWED",
    "TIER_1_MF_MICRO",
    "TIER_2_MF_MICRO",
    "TIER_3_MF_MICRO",
    "TIER_1_DP_BPS_LEASE",
    "TIER_2_DP_BPS_LEASE",
    "TIER_3_DP_BPS_LEASE",
    "LEASE_TAX_BPS",
    "MILEAGE_ALLOWANCE_MIN",
    "MILEAGE_ALLOWANCE_MAX",
    "PENALTY_PER_MILE_CENTS",
    "PURCHASE_OPTION_FEE_CENTS",
    "DISPOSITION_FEE_CENTS",
    "UPLIFT_THRESHOLD",
    "APR_UPLIFT_BPS",
    "PREPAYMENT_PENALTY_BPS",
    "GAP_PREMIUM_BPS",
    "CLOCK_ADVANCE_MIN",
    "CLOCK_ADVANCE_MAX",
    "DAYS_PER_PERIOD",
    "DEFAULT_GRACE_DAYS_BEHAVIORAL",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
