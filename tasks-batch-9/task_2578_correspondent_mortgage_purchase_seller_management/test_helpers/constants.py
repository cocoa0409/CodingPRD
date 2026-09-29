"""Domain thresholds and numeric constants stated in the PRD.

Every value here is quoted verbatim from the PRD's business rules; nothing is
invented and nothing is derived.
"""

# ─── The logical clock (PRD §2.4) ───────────────────────────────────────────
CLOCK_START = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ──────────────────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# ─── Seller approval gates (PRD §3.2) ───────────────────────────────────────
APPROVAL = {
    "STATEMENT_STALENESS_DAYS": 455,
    "MIN_TANGIBLE_NET_WORTH_CENTS": 250_000_000,
    "MIN_LIQUID_ASSETS_CENTS": 50_000_000,
    "EXPOSURE_MULTIPLIER_PASS": 10,
    "EXPOSURE_MULTIPLIER_CONDITIONAL_PASS": 5,
    "EXPOSURE_ABSOLUTE_CAP_CENTS": 5_000_000_000,
}

# ─── Quality-control review outcome derivation (PRD §3.1) ───────────────────
QC_OUTCOME = {
    "CRITICAL_FINDINGS_FAIL_THRESHOLD": 1,
    "FINDINGS_CONDITIONAL_PASS_THRESHOLD": 5,
}

# ─── Product eligibility matrix bounds (PRD §3.3) ───────────────────────────
PRODUCT_BOUNDS = {
    "PRODUCT_CODE_MIN_LEN": 3,
    "PRODUCT_CODE_MAX_LEN": 32,
    "BASE_PRICE_PCT_MIN": 90.000,
    "BASE_PRICE_PCT_MAX": 110.000,
    "FICO_MIN": 300,
    "FICO_MAX": 850,
    "MAX_LTV_PCT_MIN": 1.0,
    "MAX_LTV_PCT_MAX": 100.0,
    "SRP_PCT_MIN": 0.000,
    "SRP_PCT_MAX": 5.000,
    "ADJUSTMENT_CODE_MIN_LEN": 3,
    "ADJUSTMENT_CODE_MAX_LEN": 48,
    "PRICE_ADJUSTMENT_BPS_MIN": -300,
    "PRICE_ADJUSTMENT_BPS_MAX": 100,
}

# ─── Commitment lock pricing (PRD §3.4) ─────────────────────────────────────
COMMITMENT = {
    "MIN_NOTIONAL_CENTS": 1_000_000,
    "MAX_LOCK_TERM_DAYS": 60,
    "MANDATORY_TYPE_SPREAD_BPS": 25,
    "BEST_EFFORTS_TYPE_SPREAD_BPS": -35,
    "PRICE_FLOOR_PCT": 98.000,
    "PRICE_CEILING_PCT": 104.000,
    "TOLERANCE_PCT": 2.00,
}

# The lock-term tier table: term in days -> basis points contributed.
LOCK_TERM_BPS_TABLE = {15: 0, 30: -12, 45: -25, 60: -40}

# ─── Commitment retirement fees (PRD §3.5) ──────────────────────────────────
PAIR_OFF = {
    "ADMINISTRATIVE_FEE_CENTS": 25_000,
}

# ─── Purchase review windows (PRD §3.6) ─────────────────────────────────────
CURE_WINDOW_DAYS = {"LOW": 15, "MEDIUM": 10, "HIGH": 5}
SUSPENSE_CONDITION_DAYS = 7

# ─── Purchase advice pricing (PRD §3.7) ─────────────────────────────────────
ADVICE = {
    "VOLUME_TIER_ONE_CENTS": 100_000_000,
    "VOLUME_TIER_ONE_BPS": 5,
    "VOLUME_TIER_TWO_CENTS": 250_000_000,
    "VOLUME_TIER_TWO_BPS": 10,
    "INTEREST_YEAR_BASIS_DAYS": 360,
    "WIRE_FEE_CENTS": 3_500,
    "EXPIRED_DEFECT_PENALTY_BPS": -50,
}

# ─── Repurchase demands and escrow transfer (PRD §3.8) ──────────────────────
REPURCHASE = {
    "ADMIN_FEE_CENTS": 50_000,
    "APPEAL_WINDOW_DAYS": 30,
    "EPD_WINDOW_DAYS": 120,
    "ESCROW_TRANSFER_DAYS": 15,
}

# ─── Scorecard grading (PRD §3.9) ───────────────────────────────────────────
SCORECARD = {
    "MIN_SCORED_LOANS": 2,
    "GRADE_A_MAX_BPS": 1000,
    "GRADE_B_MAX_BPS": 2500,
    "GRADE_C_MAX_BPS": 5000,
    "WATCH_THRESHOLD_BPS": 1000,
    "SUSPEND_THRESHOLD_BPS": 5000,
}

# ─── Values reused by tests when the exact figure does not matter ───────────
TEST_DEFAULTS = {
    "SELLER_LEGAL_NAME": "Harbor Point Mortgage LLC",
    "SELLER_TIN": "823391045",
    "SELLER_TYPE": "NON_BANK_IMB",
    "FISCAL_YEAR_END": "2025-12-31",
    "TANGIBLE_NET_WORTH_CENTS": 300_000_000,
    "LIQUID_ASSETS_CENTS": 80_000_000,
    "PRODUCT_CODE": "CONF30F",
    "BASE_PRICE_PCT": 101.250,
    "MIN_FICO": 680,
    "MAX_LTV_PCT": 95.0,
    "MAX_LOAN_AMOUNT_CENTS": 76_650_000,
    "SRP_PCT": 1.250,
    "NOTIONAL_AMOUNT_CENTS": 100_000_000,
    "DELIVERY_WINDOW_START": "2026-08-01",
    "DELIVERY_EXPIRY_DATE": "2026-08-31",
    "REFERENCE_FICO": 720,
    "REFERENCE_LTV_PCT": 82.5,
    "NOTE_AMOUNT_CENTS": 40_000_000,
    "NOTE_RATE_PCT": 6.500,
    "FICO": 720,
    "LTV_PCT": 82.5,
    "CLOSING_DATE": "2026-07-28",
    "FIRST_PAYMENT_DUE_DATE": "2026-09-01",
}
