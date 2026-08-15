"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # PRD §3.2/§3.6: fallout radius per shell inch
    "SPECTATOR_FT_PER_SHELL_INCH": 70,
    # PRD §3.6: wind adjustment
    "DRIFT_THRESHOLD_MPH": 8,
    "DRIFT_FACTOR_PER_MPH": 0.05,
    "DRIFT_FACTOR_CAP": 1.5,
    # PRD §3.3/§3.8: standby fee
    "STANDBY_BASE_FEE_CENTS": 25000,
    "STANDBY_HOURLY_RATE_CENTS": 14500,
    "ENGINE_SURCHARGE_CENTS": 30000,
    # PRD §3.5: guard spacing
    "GUARD_SPACING_FT": 100,
    # PRD §3.7: dud-rate auto-halt
    "DUD_HALT_MIN": 2,
    "DUD_RATE_LIMIT": 0.05,
    # PRD §3.6: weather windows / limits
    "WEATHER_VALIDITY_MIN": 30,
    "GO_NO_GO_WINDOW_MIN": 60,
    "WIND_SUSTAINED_LIMIT_MPH": 20,
    "WIND_GUST_LIMIT_MPH": 25,
    # PRD §3.7: misfire soak
    "SOAK_MINUTES": 15,
    # PRD §3.2: venue booking trailing buffer
    "VENUE_BUFFER_MIN": 120,
}

TEST_DEFAULTS = {
    "LICENSE_VALID_FROM": "2026-01-01T00:00:00Z",
    "LICENSE_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "CERT_EXPIRES_AT": "2027-06-01T00:00:00Z",
    "INSPECTION_DUE_AT": "2027-01-01T00:00:00Z",
    "SHOW_START": "2026-09-01T20:00:00Z",
    "SHOW_END": "2026-09-01T23:00:00Z",
    "MAGAZINE_CAPACITY_LBS": 100.00,
    "BATCH_UNITS": 50,
    "NEW_PER_UNIT_LBS": 0.50,
    "DECLARED_DIAMETER_IN": 4,
    "BOUNDARY_FT": 300,
    "STRUCTURE_FT": 500,
}
