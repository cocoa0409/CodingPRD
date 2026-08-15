"""Domain thresholds and pricing constants from the PRD (§3 calculation rules)."""

# Logical clock default at server start (PRD §2.5)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Line pricing (PRD §3.2)
SHAPE_AREA_FACTOR = {"RECTANGLE": 1.0, "ARCH": 0.85, "CIRCLE": 0.785, "TRAPEZOID": 0.9}
GRID_ADDER_CENTS = {"NONE": 0, "COLONIAL": 4000, "PRAIRIE": 5500, "DIAMOND": 7000}
HARDWARE_ADDER_CENTS = {"STANDARD": 0, "BRUSHED_NICKEL": 2500, "OIL_RUBBED_BRONZE": 3200}

# Volume discount tiers (PRD §3.2): pre-discount subtotal floors in cents
DISCOUNT_TIERS = [
    (5_000_000, 0.12),
    (2_000_000, 0.08),
    (500_000, 0.05),
]

# NFRC certified rating derates (PRD §3.3)
ARGON_DERATE_PER_PT = 0.002
SPACER_DERATE = {"ALUMINUM": 0.01, "WARM_EDGE": 0.0}

# Remake chain cap (PRD §3.5): at most three remakes per original unit
MAX_REMAKES_PER_UNIT = 3

# Warranty coverage windows in years (PRD §3.7)
COMPONENT_WINDOW_YEARS = {"FRAME": 20, "IG_SEAL": 20, "HARDWARE": 10, "GRID": 10, "GLASS": 2}
WHOLE_UNIT_WINDOW_YEARS = 15

# Service-part carrier flat fees in cents (PRD §3.7)
CARRIER_FEE_CENTS = {"PARCEL": 2500, "STANDARD_FREIGHT": 8000, "EXPEDITED": 15000}

# Standard reference fixtures used across the suite (PRD §3 worked examples)
V200_PAYLOAD = {
    "series_code": "V200",
    "frame_material": "VINYL",
    "base_rate_cents_per_ui": 1500,
    "min_billable_sqft": 3.0,
    "max_united_inches": 120,
    "special_shape_upcharge_pct": 40,
    "lead_time_standard_days": 10,
    "lead_time_special_shape_days": 25,
    "frame_warranty_years": 20,
}

A050_PAYLOAD = {
    "series_code": "A050",
    "frame_material": "ALUMINUM_CLAD",
    "base_rate_cents_per_ui": 1999,
    "min_billable_sqft": 1.0,
    "max_united_inches": 100,
    "special_shape_upcharge_pct": 33,
    "lead_time_standard_days": 12,
    "lead_time_special_shape_days": 20,
    "frame_warranty_years": 20,
}

GP1_PAYLOAD = {
    "code": "LP2-ARG",
    "pane_count": 2,
    "spacer_type": "ALUMINUM",
    "argon_target_pct": 95,
    "argon_min_pct": 90,
    "catalog_u_factor": 0.28,
    "catalog_shgc": 0.40,
    "price_per_sqft_cents": 900,
    "ig_warranty_years": 20,
}

GP3_PAYLOAD = {
    "code": "LP2-AZ",
    "pane_count": 2,
    "spacer_type": "ALUMINUM",
    "argon_target_pct": 90,
    "argon_min_pct": 85,
    "catalog_u_factor": 0.31,
    "catalog_shgc": 0.23,
    "price_per_sqft_cents": 700,
    "ig_warranty_years": 20,
}

MN_RULE_PAYLOAD = {
    "state_code": "MN",
    "max_u_factor": 0.30,
    "max_shgc": 0.55,
    "effective_from": "2025-01-01T00:00:00Z",
}

AZ_RULE_PAYLOAD = {
    "state_code": "AZ",
    "max_u_factor": 0.32,
    "max_shgc": 0.25,
    "effective_from": "2025-01-01T00:00:00Z",
}

# Canonical dates used across setups
ORDER_DATE = "2026-08-02T00:00:00Z"
WAVE_DATE = "2026-09-01T00:00:00Z"
LOAD_DATE = "2026-09-02T00:00:00Z"
SHIP_DATE = "2026-09-05T00:00:00Z"
DELIVERED_CLOCK = "2026-09-05T00:00:00Z"
