"""Domain thresholds — numeric constants named in the PRD (§2.5, §3.2, §3.4, §3.6, §3.7)."""

# Cold-chain temperature thresholds in Fahrenheit (PRD §3.4): strictly-above rule.
COLD_CHAIN_THRESHOLD_HIGH_MEDIUM_F = 41.0
COLD_CHAIN_THRESHOLD_LOW_F = 55.0

# Donation valuation per-pound prices in integer cents keyed on crop_code (PRD §3.6).
PRICE_PER_LB_CENTS = {
    "SWEET_CORN": 33,
    "APPLES": 41,
    "LEAFY_GREENS": 74,
    "TOMATOES": 58,
    "ROOT_VEG": 29,
    "WINTER_SQUASH": 36,
}
DEFAULT_PRICE_CENTS = 40

# Impact metrics: meals per gleaned pound (PRD §3.7).
MEALS_PER_LB = 1.2

# Volunteer standing: no-show count reaching this threshold suspends (PRD §3.2).
NO_SHOW_SUSPEND_THRESHOLD = 2

# Logical clock startup instant (PRD §2.5).
CLOCK_STARTUP_ISO = "2026-08-01T00:00:00Z"
