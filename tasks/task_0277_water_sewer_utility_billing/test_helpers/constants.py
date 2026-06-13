"""Domain thresholds and canonical numeric values from the PRD calculations.

The canonical rate schedule and consumption profile below are reused by most
depth/breadth tests; their pre-computed charge values are documented inline so
boundary tests can target exact ledger states.
"""

# Pagination bounds (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Rate-schedule field defaults (PRD §3.1)
RATE_SCHEDULE_DEFAULTS = {
    "sewer_ratio_pct": 100,
    "leak_adjustment_rate_pct": 50,
    "assistance_discount_pct": 25,
    "late_fee_pct": 5,
    "arrears_shutoff_threshold_cents": 7500,
    "reconnect_fee_cents": 5000,
}

# Canonical residential rate schedule (cents) reused across tests.
#   fixed_water=1200, fixed_sewer=800
#   tiers: [0-5000 @300/kgal, 5000-15000 @500/kgal, 15000+ @800/kgal] marginal
#   sewer_rate=600/kgal, sewer_ratio=90%, uncapped
CANONICAL_RATE_SCHEDULE = {
    "name": "Res 2026",
    "fixed_water_charge_cents": 1200,
    "fixed_sewer_charge_cents": 800,
    "water_tiers": [
        {"up_to_gallons": 5000, "rate_cents_per_kgal": 300},
        {"up_to_gallons": 15000, "rate_cents_per_kgal": 500},
        {"up_to_gallons": None, "rate_cents_per_kgal": 800},
    ],
    "sewer_rate_cents_per_kgal": 600,
    "sewer_ratio_pct": 90,
}

# Canonical consumption profile: potable 12000, irrigation 8000 (total 20000).
#   water_volumetric_cents = 5000*300 + 10000*500 + 5000*800 = 10,500,000 cents*gal
#                          -> /1000 -> 10500 cents
#   billable_sewer_gallons = round_half_up(12000 * 90 / 100) = 10800
#   sewer_volumetric_cents = round_half_up(10800 * 600 / 1000) = 6480
#   fixed_charge_cents = 2000
#   amount_billed_cents = 2000 + 10500 + 6480 = 18980
CANONICAL = {
    "potable_gallons": 12000,
    "irrigation_gallons": 8000,
    "water_volumetric_cents": 10500,
    "billable_sewer_gallons": 10800,
    "sewer_volumetric_cents": 6480,
    "fixed_charge_cents": 2000,
    "amount_billed_cents": 18980,
}

# A non-existent but well-formed UUID for not-found tests.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
