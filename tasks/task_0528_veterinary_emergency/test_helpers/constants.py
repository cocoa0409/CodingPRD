"""Domain thresholds — numeric constants from PRD calculations."""

# Estimate range (PRD §3.4)
VARIANCE_UPLIFT = 0.20
TAX_RATE = 0.0725
DEPOSIT_TIER = {
    "RED": 0.80,
    "ORANGE": 0.60,
    "YELLOW": 0.50,
    "GREEN": 0.30,
}

# Payment plan schedule (PRD §3.10)
PROMO_MIN_CENTS = 100000
PROMO_MAX_MONTHS = 6
APR_MONTHLY = 0.0225

# ICU / ward per-diem board (PRD §3.7)
PER_DIEM = {
    "ICU": 180000,
    "WARD": 60000,
}

# The logical clock default before any adjustment (PRD §3.12)
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
