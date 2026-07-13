"""Domain thresholds and rate constants named in the PRD calculations."""

# Motor-pool hourly rate for reservation holds (PRD §3.2).
HOURLY_POOL_RATE_CENTS = 1500

# Fixed subrogation administration fee subtracted in the NET variant (PRD §3.6).
SUBRO_ADMIN_FEE_CENTS = 15000

# Replacement flag threshold on replacement_score (PRD §3.3): >= 70.00 flags.
FLAG_THRESHOLD = 70.00

# Shop-bay separation buffer in minutes (PRD §3.3).
BAY_BUFFER_MINUTES = 60

# Auction commission brackets (PRD §3.5).
TIER1_MAX_CENTS = 500000   # <= this: 10%
TIER2_MAX_CENTS = 2000000  # <= this: 8%; above: 6%

# Server logical clock startup default (PRD §2.7).
CLOCK_STARTUP_UTC = "2026-03-01T00:00:00Z"

# The standard SEDAN class policy used to make rate lookups deterministic across setups.
SEDAN_POLICY = {
    "vehicle_class": "SEDAN",
    "assignment_fee_cents_per_month": 30000,
    "mileage_tier1_rate_cents": 50,
    "mileage_tier2_rate_cents": 80,
    "mileage_tier_boundary_miles": 1000,
    "fuel_surcharge_multiplier": 1.1,
    "idle_free_minutes": 60,
    "idle_penalty_cents_per_min": 25,
    "replacement_age_years": 10,
    "replacement_mileage": 150000,
    "replacement_maint_ratio": 0.6,
}
