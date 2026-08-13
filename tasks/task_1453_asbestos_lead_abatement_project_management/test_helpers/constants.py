"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock (PRD section 2.4): startup value of the server-managed clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Negative-air sizing (PRD section 3.4)
    "MACHINE_CFM": 2000,
    "ACH_FULL": 4,
    "ACH_MINI_ENCLOSURE": 6,
    "ACH_GLOVE_BAG": 0,
    "PRESSURE_MAX_INWG": -0.020,
    # Manifest net weight / fees (PRD section 3.7)
    "BAG_TARE_LBS": 2,
    "LBS_PER_TON": 2000,
    "TIER1_MAX_TONS": 10,
    "TIER1_CENTS_PER_TON": 15000,
    "TIER2_CENTS_PER_TON": 12500,
    # Estimated disposal cost density assumption (PRD section 3.7)
    "EST_LBS_PER_SQFT": 1.5,
    # Project cost rollup (PRD section 3.7)
    "SURCHARGE_RATE": 0.08,
    # Regulatory waiting period (PRD section 3.3)
    "WAIT_STANDARD_DAYS": 10,
    "WAIT_EMERGENCY_DAYS": 3,
    # Clearance testing (PRD section 3.6)
    "CLEARANCE_PASS_F_CC": 0.010,
    "MIN_CLEARANCE_PASS_COUNT": 2,
    # Relocation unit cleaning buffer (PRD section 3.8)
    "UNIT_CLEANING_BUFFER_DAYS": 1,
}

TEST_DEFAULTS = {
    "BASE_ABATEMENT_COST_CENTS": 5_000_000,
    "WORK_AREA_VOLUME_CUFT": 240_000,
    "SAMPLE_QTY_SQ_FT": 100,
    "FACILITY_CAPACITY_TONS": 50,
    "FUTURE_EXPIRY": "2027-01-01T00:00:00Z",
    "SUPERVISOR_WINDOW_START": "2026-08-01T00:00:00Z",
    "SUPERVISOR_WINDOW_END": "2026-09-01T00:00:00Z",
    "WORK_START_CLOCK": "2026-08-11T00:00:00Z",
}
