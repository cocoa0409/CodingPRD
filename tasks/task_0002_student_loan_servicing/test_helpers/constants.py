"""Domain thresholds — numeric constants from PRD calculations.

Mirrors the constants block in the calculations section of the source-of-truth
spec; tests reference these by name rather than re-typing literals.
"""

# Poverty line annual values in cents per family_size (PRD §3.3 table).
POVERTY_LINES_BY_STATE = {
    "CONTIGUOUS": {
        1: 1_506_000,
        2: 2_034_000,
        3: 2_562_000,
        4: 3_090_000,
        5: 3_618_000,
    },
    "AK": {
        1: 1_883_000,
        2: 2_542_000,
        3: 3_201_000,
        4: 3_860_000,
        5: 4_519_000,
    },
    "HI": {
        1: 1_732_000,
        2: 2_339_000,
        3: 2_946_000,
        4: 3_553_000,
        5: 4_160_000,
    },
}

# IDR formula constants (§3.3).
IBR_DISCRETIONARY_THRESHOLD_PCT = 150
PAYE_DISCRETIONARY_THRESHOLD_PCT = 150
SAVE_DISCRETIONARY_THRESHOLD_PCT = 225

IBR_PAYMENT_PCT = 0.15
PAYE_PAYMENT_PCT = 0.10
SAVE_PAYMENT_PCT = 0.05

STANDARD_TERM_MONTHS = 120

# Payment allocation (§3.4).
TREASURY_OFFSET_FEE_PCT = 0.1825

# Interest accrual (§2.7) — 365 (not 360) for federal Direct loans.
DAILY_ACCRUAL_BASIS_DAYS = 365

# PSLF (§3.6).
PSLF_REQUIRED_COUNT = 120
ON_TIME_BACK_WINDOW_DAYS = 0
ON_TIME_FORWARD_WINDOW_DAYS = 15

# Delinquency → default boundary (§3.5).
DEFAULT_THRESHOLD_DAYS = 270

# Payment back-date window (§3.4).
PAYMENT_BACKDATE_WINDOW_DAYS = 15

# Payment reversal window (§3.4).
PAYMENT_REVERSAL_WINDOW_DAYS = 30

# Far-future sentinel for ongoing employment certifications (§3.6).
ONGOING_CERTIFICATION_END = "2999-12-31"
