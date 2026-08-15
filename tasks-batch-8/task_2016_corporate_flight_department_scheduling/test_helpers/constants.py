"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# --- SIFL banding (PRD settlement section) ---
BAND_1_MAX_MILES = 500
BAND_2_MAX_MILES = 1500

# --- Aircraft selector / interval rules (PRD assignment section) ---
TURN_BUFFER_MINUTES = 90

# --- Crew duty time (PRD crewing section): 840 minutes == fourteen hours ---
DUTY_LIMIT_MINUTES = 840
DUTY_WINDOW_HOURS = 24

# --- Owned-fleet per-minute cost rates in cents (PRD settlement section) ---
COST_PER_MINUTE_CENTS = {
    "LIGHT_JET": 8500,
    "MIDSIZE_JET": 14000,
    "HEAVY_JET": 23000,
    "TURBOPROP": 5000,
}

# --- Clock defaults (PRD logical-clock section) ---
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# --- Shared SIFL rate-period template used by fixtures ---
DEFAULT_RATE_PERIOD = {
    "period_start_utc": "2026-08-01T00:00:00Z",
    "period_end_utc": "2027-02-01T00:00:00Z",
    "terminal_charge_cents": 5000,
    "rate_band_1_cents_per_mile": 30,
    "rate_band_2_cents_per_mile": 20,
    "rate_band_3_cents_per_mile": 10,
    "control_employee_multiplier_pct": 400,
}
