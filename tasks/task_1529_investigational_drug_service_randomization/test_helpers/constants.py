"""Domain thresholds and pinned constants (PRD §2.5, §2.9, §3.4, §3.6)."""

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Excursion severity constants (PRD §3.4).
SEVERITY = {
    "MAX_CREDITABLE_MINUTES": 1440,
    "DEGREE_STEP": 2,
    "MULT_BOTH_SIDES": 4,
    "MULT_BELOW_ONLY": 3,
    "MULT_ABOVE_ONLY": 2,
}

# Dispensing visit window: nominal = randomized_at + 28 * (visit_number - 1) days,
# permitted within the closed interval nominal +/- 3 days (PRD §3.6).
VISIT_WINDOW = {
    "VISIT_PERIOD_DAYS": 28,
    "WINDOW_PLUS_MINUS_DAYS": 3,
}

# Destruction facility buffer in minutes (PRD §3.7).
DESTRUCTION_BUFFER_MINUTES = 30

# Default storage range / budget used by factories (PRD §3.2).
LOT_DEFAULTS = {
    "STORAGE_MIN_C": 2,
    "STORAGE_MAX_C": 8,
    "STABILITY_BUDGET_MINUTES": 600,
    "EXPIRY_DATE": "2027-06-01T00:00:00Z",
}
