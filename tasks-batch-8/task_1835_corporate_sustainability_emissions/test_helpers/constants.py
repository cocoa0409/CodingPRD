"""Domain thresholds — numeric constants named in the PRD (§2.5, §3.2-§3.8)."""

THRESHOLDS = {
    # Begin-assurance gate: readiness must be at least 80.0 (PRD §3.2).
    "READINESS_MIN_PCT": 80.0,
    # Evidence mandate: records with quantity >= 1000 need verified evidence (PRD §3.3).
    "EVIDENCE_MANDATE_QUANTITY": 1000,
    # Trajectory tolerance in percentage points (PRD §3.8).
    "TRAJECTORY_TOLERANCE_PCT_POINTS": 2.0,
    # Baseline shift significance boundary (PRD §3.8).
    "BASELINE_SIGNIFICANCE_PCT": 5.0,
    # Instrument vintage window: reporting_year - 3 <= vintage <= reporting_year (PRD §3.6).
    "VINTAGE_WINDOW_YEARS": 3,
    # Evidence retention: cycle year end + 7 years (PRD §3.4).
    "RETENTION_YEARS": 7,
}

# The logical clock reads exactly this instant at server startup (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical validity windows used by factor fixtures: a full calendar year,
# both endpoints inclusive (PRD §3.1 closed windows).
def year_window(year: int) -> tuple:
    return (f"{year}-01-01T00:00:00Z", f"{year}-12-31T23:59:59Z")


TEST_DEFAULTS = {
    "COUNTRY_CODE": "US",
    "GRID_REGION": "CA",
    "FUEL_FACTOR_VALUE": 0.5,       # tCO2e per therm
    "GRID_FACTOR_VALUE": 0.4,       # tCO2e per MWh
    "RESIDUAL_FACTOR_VALUE": 0.5,   # tCO2e per MWh
    "EEIO_FACTOR_VALUE": 0.0005,    # tCO2e per USD
    "REPORTING_YEAR": 2026,
}
