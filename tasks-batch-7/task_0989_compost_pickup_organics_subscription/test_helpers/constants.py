"""Domain thresholds and plan defaults from the PRD's calculation narratives."""

THRESHOLDS = {
    "SKIP_CUTOFF_HOURS": 48,           # PRD §3.5 skip cutoff
    "STRIKE_SUSPENSION_THRESHOLD": 3,  # PRD §3.6 strike suspension
    "CREDIT_CAP_PCT": 0.5,             # PRD §3.9 invoice credit cap (floor)
    "COMPOST_YIELD": 0.3,              # PRD §3.8 produced_kg fraction
    "BAG_KG": 10,                      # PRD §3.8 kilograms per bag
    "BAG_PRICE_CENTS": 500,            # PRD §3.8 cents per bag
    "INVOICE_DUE_DAYS": 14,            # PRD §3.9 due_date offset
    "CO2E_PER_KG": 0.5,                # PRD §3.8 impact report factor
    "ESCALATOR_STEP": 0.5,             # PRD §3.6 strike escalator step
}

SEASON_MULTIPLIERS = {
    "SPRING": 1.0,
    "SUMMER": 1.2,
    "FALL": 1.0,
    "WINTER": 0.8,
}

SURCHARGE_BASE_CENTS = {"LOW": 500, "MEDIUM": 1000, "HIGH": 1500}
SURCHARGE_TYPE_MULTIPLIER = {"RESIDENTIAL": 1.0, "COMMERCIAL": 2.0}

# Canonical plan fixtures used across the suite (same literals throughout).
PLAN_RES_DEFAULTS = {
    "code": "RES",
    "name": "Residential",
    "subscriber_type": "RESIDENTIAL",
    "bin_type": "BIN_35L",
    "included_bins": 1,
    "weekly_price_cents": 1200,
    "metered_base_cents": 0,
    "per_kg_rate_cents": 0,
    "included_kg_per_week": 0,
    "credit_rate_cents_per_kg": 10,
    "skip_allowance_per_quarter": 2,
}

PLAN_COM_DEFAULTS = {
    "code": "COM",
    "name": "Commercial",
    "subscriber_type": "COMMERCIAL",
    "bin_type": "BIN_240L",
    "included_bins": 1,
    "weekly_price_cents": 0,
    "metered_base_cents": 3000,
    "per_kg_rate_cents": 7,
    "included_kg_per_week": 40,
    "credit_rate_cents_per_kg": 5,
    "skip_allowance_per_quarter": 4,
}

# Nominal bin capacities used by the canonical plans.
BIN_CAPACITY_KG = {"BIN_35L": 20, "BIN_240L": 60}

# The logical clock starts here on every fresh server (PRD §2.4).
CLOCK_START = "2026-05-01T00:00:00Z"
