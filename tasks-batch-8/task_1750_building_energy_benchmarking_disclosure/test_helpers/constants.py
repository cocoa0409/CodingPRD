"""Domain thresholds and shared fixture constants (PRD §2.5, §2.6, §3)."""

# Logical clock default before any set_current_utc call (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Fixed conversion factors to kBtu (PRD §2.6).
COMMODITY_KBTU_FACTOR = {
    "ELECTRICITY": 3.412,
    "NATURAL_GAS": 100,
    "DISTRICT_STEAM": 1194,
    "FUEL_OIL": 138.5,
}

# Domain thresholds (PRD §3.6, §3.7).
THRESHOLDS = {
    "SCORE_MIN_COMPLETENESS_PCT": 75,
    "OWNER_RESTRICTION_THRESHOLD_CENTS": 100000,
    "SCORE_BASE": 50,
    "SCORE_MIN": 1,
    "SCORE_MAX": 100,
    "MAX_EXTENSION_DAYS": 90,
}

# Standard performance-standard entry used by the shared cycle fixture.
OFFICE_STANDARD = {
    "property_type": "OFFICE",
    "median_eui": 80,
    "score_slope": 2,
    "baseline_eui_default": 100,
    "annual_reduction_pct": 10,
    "shortfall_tolerance_pct": 5,
    "fine_rate_cents_per_sqft": 5,
    "performance_fine_cap_cents": 1000000,
}

# Standard cycle configuration used across the test suite (PRD §3.1 fields).
CYCLE_DEFAULTS = {
    "cycle_year": 2027,
    "filing_deadline_at": "2027-06-01T00:00:00Z",
    "covered_floor_area_threshold_sqft": 25000,
    "covered_property_types": ["OFFICE", "MULTIFAMILY", "RETAIL", "HOTEL"],
    "late_fine_daily_rate_cents": 5000,
    "late_fine_cap_days": 60,
    "non_compliance_fine_cents": 500000,
    "data_completeness_min_pct": 90,
    "correction_tolerance_pct": 5,
    "anomaly_yoy_threshold_pct": 25,
    "weather_adjustment_factor": 0.9,
    "performance_standards": [OFFICE_STANDARD],
}

# Default building geometry: 50000 sqft gross, three units totalling 40000 sqft,
# leaving 10000 sqft of owner-controlled common area (PRD §3.5 completeness).
DEFAULT_UNIT_SPECS = [
    ("U1", 20000, "OFFICE"),
    ("U2", 15000, "RETAIL"),
    ("U3", 5000, "OFFICE"),
]

# Two compact units totalling 30000 of 50000 sqft -> 100.00 completeness when
# both are consented (common area 20000 + consented 30000).
FULL_COVERAGE_UNIT_SPECS = [
    ("U1", 20000, "OFFICE"),
    ("U2", 10000, "RETAIL"),
]
