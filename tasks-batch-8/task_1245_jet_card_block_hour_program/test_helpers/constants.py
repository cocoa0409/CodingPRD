"""Domain thresholds and shared test constants from PRD pricing/ledger rules."""

# Default program parameters used by factories/fixtures unless overridden.
DEFAULT_PROGRAM = {
    "aircraft_category": "LIGHT",
    "hours_purchased": 25,
    "purchase_price_cents": 10_000_000,
    "swap_ratio_to_lower": 0.90,
    "swap_ratio_to_higher": 1.25,
    "expiry_months": 18,
    "taxi_minutes_per_leg": 12,
    "min_billable_minutes_per_leg": 60,
    "peak_surcharge_pct": 0.15,
    "availability_window_hours": 24,
    "round_trip_discount_pct": 0.10,
    "early_termination_penalty_pct": 0.20,
    "fractional_upgrade_ratio": 0.0625,
}

THRESHOLDS = {
    # Per-leg billing floor: billable_minutes never below min_billable_minutes_per_leg.
    "MIN_BILLABLE_MINUTES_PER_LEG": 60,
    "TAXI_MINUTES_PER_LEG": 12,
    # Early-termination penalty applies before the first anniversary (12 months).
    "EARLY_TERMINATION_MONTHS": 12,
    # Minimum fractional conversion unit.
    "MIN_SHARE_DENOMINATOR": 16,
    # Assumed cruise speed for quotes.
    "CRUISE_KNOTS": 400,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-06-01T00:00:00Z",
    "HOME_BASE": "KTEB",
    "DESTINATION": "KPBI",
    "MEMBER_EMAIL_DOMAIN": "x.com",
}
