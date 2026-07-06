"""Domain thresholds — numeric constants from PRD service-level and analytics rules."""

# Provisional-deadline default windows (hours), keyed by case category.
DEFAULT_WINDOW_HOURS = {
    "IMMIGRATION": 168,
    "HEALTHCARE": 120,
    "HOUSING": 120,
    "TAX": 72,
    "BENEFITS": 96,
    "OTHER": 168,
}

# Final-deadline priority multipliers.
PRIORITY_MULTIPLIER = {
    "LOW": 1.5,
    "NORMAL": 1.0,
    "HIGH": 0.5,
    "URGENT": 0.25,
}

# Final-deadline per-category surcharge (hours).
CATEGORY_SURCHARGE_HOURS = {
    "IMMIGRATION": 24,
    "HEALTHCARE": 12,
    "HOUSING": 12,
    "TAX": 0,
    "BENEFITS": 0,
    "OTHER": 0,
}

MAX_WINDOW_HOURS = 720

# Recurring-issue index weights.
PRIORITY_WEIGHT = {
    "LOW": 0.5,
    "NORMAL": 1.0,
    "HIGH": 2.0,
    "URGENT": 3.5,
}
RECENCY_BONUS = 1.25
DEFAULT_WINDOW_DAYS = 30

# Newsletter cost model.
BASE_POSTAGE_CENTS = 55
PRINT_CENTS_PER_PAGE = 8

# Logical-clock startup default.
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"
