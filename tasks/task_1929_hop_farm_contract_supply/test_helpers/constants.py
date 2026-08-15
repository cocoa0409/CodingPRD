"""Domain thresholds and constants from the PRD's calculation rules (§3)."""

# PRD §3.1 / §3.8: per-acre base yield table shared by projections and guarantees.
VARIETY_BASE_YIELD_LBS_PER_ACRE = {
    "CASCADE": 1800,
    "CENTENNIAL": 2000,
    "CTZ": 2200,
    "CITRA": 1900,
    "MOSAIC": 1700,
}

# PRD §3.2: kiln drying physics and the moisture safety gate.
BONE_DRY_FLOOR_FRACTION = 0.24
MOISTURE_RELEASE_MAX_PCT = 10.0
KILN_BUFFER_MINUTES = 30

# PRD §3.4: pelletizing processing loss.
PROCESSING_LOSS_PCT = 0.08

# PRD §3.5: alpha-adjusted pricing floor.
MIN_PRICE_CENTS_PER_LB = 100

# PRD §3.8: default coverage share at claim filing.
DEFAULT_COVERAGE_PCT = 0.75

# PRD §3.9: carryover decay at crop-year rollover.
STORAGE_GRACE_MONTHS = 6
MONTHLY_DECAY_RATE = 0.01

# PRD §2.5: startup value of the server-held logical clock.
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Standard non-conflicting kiln windows on a single kiln (30-minute buffer
# respected between consecutive windows).
WINDOW_DAY1_AM = ("2026-08-20T08:00:00Z", "2026-08-20T12:00:00Z")
WINDOW_DAY1_PM = ("2026-08-20T12:30:00Z", "2026-08-20T16:00:00Z")
WINDOW_DAY2_AM = ("2026-08-21T08:00:00Z", "2026-08-21T12:00:00Z")
WINDOW_DAY2_PM = ("2026-08-21T12:30:00Z", "2026-08-21T16:00:00Z")
