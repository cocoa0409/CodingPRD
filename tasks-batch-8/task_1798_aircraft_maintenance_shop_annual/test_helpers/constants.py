"""Domain thresholds and defaults drawn from the PRD's calculation rules."""

THRESHOLDS = {
    # Shop-supplies surcharge tier: 5% below this parts total, 8% at-or-above.
    "SHOP_SUPPLIES_TIER_CENTS": 50000,
    "SHOP_SUPPLIES_LOW_RATE": 0.05,
    "SHOP_SUPPLIES_HIGH_RATE": 0.08,
    # Sales-tax rate applied to labor + parts + supplies (hangar fee exempt).
    "TAX_RATE": 0.0825,
    # Mechanic daily capacity: same-day cumulative billable time plus a
    # thirty-minute buffer must not exceed ten billable hours.
    "MECHANIC_DAILY_CAP_TENTHS": 100,
    "MECHANIC_BUFFER_TENTHS": 3,
    # Hangar-slot maximum window.
    "SLOT_MAX_DAYS": 30,
    # Default owner approval cap (cents) when approval_cap_cents is omitted.
    "DEFAULT_APPROVAL_CAP_CENTS": 50000,
    # Warranty window: return-to-service instant plus ninety days.
    "WARRANTY_DAYS": 90,
    # Smallest billable labor increment in tenths of an hour.
    "LABOR_INCREMENT_TENTHS": 3,
}

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 9000,
    "DAILY_RATE_CENTS": 10000,
    "FLAT_RATE_CENTS": 1000,
    "APPROVAL_CAP_CENTS": 100000,
}

LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"
