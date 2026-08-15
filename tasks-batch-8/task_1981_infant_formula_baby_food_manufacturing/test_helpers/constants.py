"""Domain thresholds — numeric constants from PRD §2.9 and §3."""

# PRD §2.9: before any operator intervention the logical clock is initialized
# to this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD §3.4: borderline variant safety margins for INF-0-6M profiles.
INFANT_SAFETY_MARGIN_MIN = 1.02
INFANT_SAFETY_MARGIN_MAX = 0.98

# PRD §3.2: audit result thresholds (2 decimal places, round half-up).
AUDIT_PASS_THRESHOLD = 75.00
AUDIT_FAIL_THRESHOLD = 50.00
AUDIT_RECENCY_WINDOW_DAYS = 365

# PRD §3.2: risk-rating recency decay constants.
RECENCY_DECAY_PERIOD_DAYS = 730
MIN_RECENCY_FACTOR = 0.5
LOW_RISK_THRESHOLD = 80
MEDIUM_RISK_THRESHOLD = 60

# PRD §3.4: base shelf life in calendar months by profile code.
SHELF_LIFE_MONTHS = {
    "INF-0-6M": 24,
    "INF-6-12M": 24,
    "TODDLER-12-36M": 18,
    "CEREAL-6M": 12,
    "PUREE-4M": 9,
}
DRY_BLEND_BONUS_MONTHS = 3

# PRD §3.6: recall effectiveness floors by class.
RECOVERY_FLOOR_BY_CLASS = {
    "CLASS_I": 90.00,
    "CLASS_II": 80.00,
    "CLASS_III": 70.00,
}

# PRD §2.5: kilogram quantities are stored/computed to 3 decimal places;
# allocation arithmetic truncates (floor) at the milligram step.
PRECISION_KG = 0.001
