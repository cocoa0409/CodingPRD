"""Domain thresholds and pricing constants from the Sign Fabrication &
Installation PRD (§3.2 pricing, §3.3 permit fees, §3.5 equipment tiers,
§3.7 warranty windows). Generic NON_EXISTENT_UUID comes from the framework.
"""

# ─── Estimate pricing (PRD §3.2) ─────────────────────────────────────────────
# Per-square-foot material rate in cents, by substrate.
MATERIAL_RATE_CENTS_PER_SQFT = {
    "ALUMINUM": 1800,
    "ACRYLIC": 2600,
    "STEEL": 3400,
}

# Per-color setup charge in cents.
COLOR_SETUP_CENTS = 4500

# Substrate labor multiplier applied to the color-labor amount.
SUBSTRATE_LABOR_MULT = {
    "ALUMINUM": 1.00,
    "ACRYLIC": 1.25,
    "STEEL": 1.50,
}

# Surcharge percentages (illumination first, then rush on the inflated base).
ILLUM_PCT = 0.15
RUSH_PCT = 0.20

# ─── Equipment requirement tiers (PRD §3.5) ──────────────────────────────────
# Placement height (feet) breakpoints; lower edge of each tier is inclusive.
HANDS_MAX_FT = 8     # at most 8 ft with no obstruction => NONE
LADDER_MAX_FT = 20   # above 8 ft up to and including 20 ft => LADDER

# ─── Warranty coverage windows in whole days (PRD §3.7) ──────────────────────
COVERAGE_DAYS = {
    "ELECTRICAL": 365,
    "STRUCTURAL": 1825,
    "COSMETIC": 90,
}

# ─── Permit fee table in cents (PRD §3.3) ────────────────────────────────────
PERMIT_FEE_CENTS = {
    "CITY_A": {"STRUCTURAL": 25000, "ELECTRICAL": 18000},
    "CITY_B": {"STRUCTURAL": 32000, "ELECTRICAL": 21000},
    "COUNTY_C": {"STRUCTURAL": 0, "ELECTRICAL": 12000},
}

# A far-future quote-expiry instant used by setups that never want auto-expiry.
FAR_FUTURE_ISO = "2030-01-01T00:00:00Z"
