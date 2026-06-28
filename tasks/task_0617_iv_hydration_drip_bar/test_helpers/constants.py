"""Domain thresholds — numeric constants from the PRD's calculations (§3.5, §3.11)."""

# Visit-charge waterfall (PRD §3.11)
DISCOUNT_FRACTIONS = {
    "NONE": 0.000,
    "GOLD": 0.150,
    "PLATINUM": 0.225,
}
MOBILE_SURCHARGE_CENTS = 9500

# Contraindication score weights (PRD §3.5)
SCORE_WEIGHTS = {
    "PREGNANCY": 40,
    "RENAL": 30,
    "CARDIAC": 25,
    "G6PD": 35,
    "ADVERSE": 20,
    "AGE": 10,
}
BLOCK_THRESHOLD = 60     # score >= 60 -> BLOCKED
REVIEW_THRESHOLD = 40    # 40 <= score < 60 -> REQUIRES_MD_REVIEW; < 40 -> CLEARED

# Pagination bounds (PRD §2.3)
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# Lounge operating-window defaults (PRD §3.1)
LOUNGE_DEFAULTS = {"open_minute_of_day": 480, "close_minute_of_day": 1200}

# Server startup logical clock default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that corresponds to no resource (for 404 tests).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
