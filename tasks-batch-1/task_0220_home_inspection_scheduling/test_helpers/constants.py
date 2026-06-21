"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# Inspection-type fee multiplier (PRD §3.7)
TYPE_MULTIPLIER = {
    "BUYER": 1.00,
    "SELLER": 0.90,
    "FOUR_POINT": 0.75,
    "WIND_MIT": 0.60,
}

# Inspection-type base on-site minutes (PRD §3.4)
TYPE_BASE_MINUTES = {
    "BUYER": 180,
    "SELLER": 150,
    "FOUR_POINT": 90,
    "WIND_MIT": 60,
}

# Add-on contributed minutes (PRD §3.4)
ADDON_DURATION_MINUTES = {
    "RADON": 30,
    "TERMITE": 20,
    "SEWER": 45,
}

# Defect weighting and per-defect points (PRD §3.6)
DEFECT_WEIGHT = {"MINOR": 1, "MAJOR": 4, "CRITICAL": 10}
DEFECT_POINTS = {"MINOR": 33, "MAJOR": 133, "CRITICAL": 333}

# severity_band floors over final_risk_score (PRD §3.6)
SEVERITY_BAND_MINOR_FLOOR = 1
SEVERITY_BAND_MAJOR_FLOOR = 133
SEVERITY_BAND_CRITICAL_FLOOR = 666

# Re-inspection discount band cutoffs on parent final_fee_cents (PRD §3.8)
REINSPECTION_BAND_LOW_CENTS = 50000
REINSPECTION_BAND_HIGH_CENTS = 100000
REINSPECTION_MAX_DISCOUNT = 0.90

# Eligibility / temporal constants (PRD §3.3, §3.8)
FOUR_POINT_MAX_YEAR_BUILT = 2000
MIN_REINSPECTION_GAP_HOURS = 48

# Pagination bounds (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Shared fee-schedule fixture values (used across composite setups)
FS_DEFAULTS = {
    "label": "fs",
    "base_rate_cents": 15000,
    "tier1_rate_cents_per_sqft": 12,
    "tier2_rate_cents_per_sqft": 8,
    "tier3_rate_cents_per_sqft": 5,
    "addon_radon_cents": 9900,
    "addon_termite_cents": 8500,
    "addon_sewer_cents": 12000,
}
