"""Numeric constants for the PT Rehab domain."""

# Medicare therapy cap (2026 PT/SLP)
KX_THRESHOLD_CENTS = 241_000
CAP_HARD_CENTS = 300_000

# Per-unit rate tiers
RATE_PT_DPT_CENTS = 4200
RATE_PTA_CENTS = 3500

# Evaluation surcharge by complexity
EVAL_SURCHARGE = {
    "LOW": 5000,
    "MODERATE": 7500,
    "HIGH": 10500,
}

# 8-minute rule
MIN_TIMED_MIN = 8
BAND_WIDTH_MIN = 15

# Reeval window in days
REEVAL_WINDOW_DAYS = 30
