"""Domain thresholds — numeric constants from the PRD's pricing, risk, and
windowing rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Session base rates in integer cents by procedure type (PRD §3.4).
BASE_RATE_CENTS = {
    "BROWS": 60000,
    "EYELINER": 50000,
    "LIP_BLUSH": 70000,
}

# Color surcharge tiers driven by pigment_count (PRD §3.4).
COLOR_SURCHARGE_2 = 5000
COLOR_SURCHARGE_3PLUS = 12000

# Pricing percentages (PRD §3.4, §3.8).
CORRECTIVE_UPLIFT_PCT = 0.25
ANNUAL_REFRESH_PCT = 0.50
DEPOSIT_PCT = 0.20
TOUCHUP_PCT = 0.40
BUNDLE_DISCOUNT_PCT = 0.15

# Client risk weighting and threshold (PRD §3.2).
W_MEDICAL = 8
W_ADVERSE = 12
W_SENS = 5
HIGH_RISK_THRESHOLD = 30

# No-show strike block threshold (PRD §3.2).
NO_SHOW_BLOCK_THRESHOLD = 3

# Temporal windows (PRD §3.3, §3.7, §3.8).
PATCH_READ_MIN_HOURS = 48
CANCEL_FREE_HOURS = 48
TOUCHUP_WINDOW_OPEN_DAYS = 30
TOUCHUP_WINDOW_CLOSE_DAYS = 60
ANNUAL_REFRESH_DAYS = 365
REDO_WINDOW_DAYS = 90

# Minimum legal age default (PRD §3.1).
MIN_CLIENT_AGE_DEFAULT = 18
