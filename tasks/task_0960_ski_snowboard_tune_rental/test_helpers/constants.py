"""Domain thresholds — numeric constants from the PRD's pricing and capacity rules."""

THRESHOLDS = {
    # Rental duration discount tiers (PRD Booking a Rental)
    "TIER1_DAYS": 7,
    "TIER1_DISCOUNT": 0.10,
    "TIER2_DAYS": 14,
    "TIER2_DISCOUNT": 0.20,
    "LATE_MULTIPLIER": 1.5,
    # Deposit floor (PRD From Confirm to Close)
    "DEPOSIT_MIN_PCT": 0.20,
    # DIN fitment (PRD Booking a Rental)
    "DIN_STEP": 0.25,
    "MIN_DIN": 0.75,
    "MAX_DIN": 12.0,
    "REF_SOLE_MM": 285,
    # Tune ticket services (PRD The Tuning Workshop)
    "RUSH_MULT": 1.5,
    "JUNIOR_MULT": 0.8,
    "STANDARD_TURNAROUND_HOURS": 48,
    "RUSH_TURNAROUND_HOURS": 24,
    "REWORK_LIMIT": 2,
    # Season leases (PRD Junior Season Leases)
    "JUNIOR_MAX_AGE": 12,
    "GUARDIAN_MIN_AGE": 18,
    "SWAP_LIMIT": 2,
    "BUYOUT_VALUE_FLOOR": 0.40,
    "BUYOUT_STRAIGHT_LINE_RATE": 0.5,
    "BUYOUT_USAGE_RATE_PER_DAY": 0.01,
    # Damage (PRD Damage Assessments)
    "DAMAGE_DEPRECIATION_FLOOR": 0.30,
    "DAMAGE_DEPRECIATION_PER_30D": 0.02,
    # Demo credits (PRD Demo Days and Purchase Upgrades)
    "DEMO_LIST_DISCOUNT": 0.75,
    "CREDIT_CAP_PCT": 0.30,
    "CREDIT_VALID_DAYS": 90,
    # Standing (PRD Customer Profiles and Account Standing)
    "LATE_WATCH_THRESHOLD": 3,
}

# Per-service pricing and labor (PRD The Tuning Workshop)
SERVICE_PRICE_CENTS = {
    "WAX": 2500,
    "EDGE_TUNE": 3000,
    "BASE_GRIND": 4500,
    "BINDING_ADJUST": 2000,
}
SERVICE_LABOR_MINUTES = {
    "WAX": 45,
    "EDGE_TUNE": 60,
    "BASE_GRIND": 90,
    "BINDING_ADJUST": 30,
}

# Damage severity percentages (PRD Damage Assessments)
SEVERITY_PCT = {
    "COSMETIC": 0.10,
    "MINOR": 0.25,
    "MAJOR": 0.50,
    "TOTAL_LOSS": 1.00,
}

TEST_DEFAULTS = {
    "BASE_DAILY_RATE_CENTS": 4000,
    "PURCHASE_PRICE_CENTS": 60000,
    "CAPACITY_BASE_MINUTES": 480,
    "CAPACITY_RUSH_MINUTES": 120,
    "LEASE_DEPOSIT_CENTS": 10000,
}

# Startup value of the logical clock before any set call (PRD The Shop's Logical Clock)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
