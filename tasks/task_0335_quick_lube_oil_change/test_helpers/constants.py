"""Domain thresholds and test defaults from the Quick Lube & Oil Change PRD calculations.

Numeric constants are quoted directly from PRD §2.7 / §3.6 / §3.10 narratives.
"""

# Pricing / projection constants (PRD §2.7, §3.6, §3.10)
THRESHOLDS = {
    # Assumed daily driving distance used to project the mileage-vs-time basis (§3.10).
    "ASSUMED_DAILY_MILES": 40,
    # Default discount cap fraction when max_discount_pct is omitted (§3.1).
    "DEFAULT_MAX_DISCOUNT_PCT": 0.50,
    # Default technician cleanup buffer between consecutive jobs, in seconds (§3.1).
    "DEFAULT_CLEANUP_BUFFER_SECONDS": 300,
}

# Common payload defaults reused across fixtures and factories.
TEST_DEFAULTS = {
    "TAX_RATE": 0.0825,
    "TARGET_THROUGHPUT_SECONDS": 1800,
    "PACKAGE_BASE_PRICE_CENTS": 6995,
    "INCLUDED_QUARTS": 5,
    "LABOR_MINUTES": 20,
    "INTERVAL_MILES": 5000,
    "INTERVAL_DAYS": 180,
    "CLOCK_ISO": "2026-06-14T09:00:00Z",
}
