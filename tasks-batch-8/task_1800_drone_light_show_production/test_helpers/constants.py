"""Domain thresholds and constants from the PRD's calculation rules.

Every value below is stated in the PRD prose: pricing tiers and fees,
crowd-distance coefficients, wind derates, battery thresholds, cycle
limits, and the logical clock's startup default.
"""

# --- Logical clock (PRD: startup default reading) ---
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# --- Contract pricing (PRD section 3.1) ---
PRICING = {
    "BASE_FEE_CENTS": 500000,
    "SURCHARGE_TIER_CENTS": 1000000,
    "DRONE_FEE_TIER1_CENTS": 2500,   # each of the first 100 drones
    "DRONE_FEE_TIER2_CENTS": 2200,   # each of the next 200 (101st-300th)
    "DRONE_FEE_TIER3_CENTS": 2000,   # every drone beyond 300
    "TIER1_MAX_DRONES": 100,
    "TIER2_MAX_DRONES": 300,
    "SURCHARGE_HIGH_RATE": 0.08,
    "SURCHARGE_LOW_RATE": 0.05,
    "DEPOSIT_RATE": 0.30,
}

# --- Cancellation refund (PRD section 3.7) ---
REFUND = {
    "ADMIN_FEE_CENTS": 25000,
    "T1_MIN_LEAD_HOURS": 336,   # fourteen days
    "T2_MIN_LEAD_HOURS": 168,   # seven days
    "T3_MIN_LEAD_HOURS": 72,    # three days
}

# --- Crowd distance / perimeter (PRD section 3.4) ---
CROWD = {
    "BASE_M": 40,
    "ALT_COEFF": 0.4,
    "DRONE_COEFF": 1.2,
    "BUFFER_M": 15,
}

# --- Effective wind limits (PRD section 3.6) ---
WIND = {
    "BASE_WIND_KT": 18,
    "GUST_FACTOR": 1.3,
    "ALT_TIER1_MAX_FT": 200,
    "ALT_TIER2_MAX_FT": 400,
    "FLEET_TIER1_MAX": 100,
    "FLEET_TIER2_MAX": 300,
}

# --- Go/no-go evaluation (PRD section 3.6) ---
GO_NO_GO = {
    "LOOKBACK_MINUTES": 60,
    "TEMP_MIN_C": -10,
    "TEMP_MAX_C": 40,
    "GO_VALIDITY_MINUTES": 240,
}

# --- Battery derate at launch (PRD section 3.5) ---
BATTERY = {
    "LAUNCH_MIN_CHARGE_PCT": 85,
    "RECENCY_MINUTES": 120,
    "WARM_FLOOR_C": 5,        # at or above: derate 1.0
    "COLD_FLOOR_C": -5,       # at or above (and below 5): derate 0.85
    "DERATE_MILD": 0.85,
    "DERATE_SEVERE": 0.70,
}

# --- Simulation verdict (PRD section 3.2) ---
SIM = {
    "MAX_SIM_DRAW_PCT": 80,
    "DRONE_MAX_SPEED_MPS": 12.0,
}

# --- Fleet / flight reconciliation (PRD sections 3.5, 3.8) ---
FLEET = {
    "CYCLE_LIMIT": 200,
    "DEVIATION_FLAG_M": 5.0,
    "SLOT_PITCH_M": 2.0,
}

# --- Show turnaround buffer (PRD section 3.1) ---
TURNAROUND_MINUTES = 120

# --- Pagination (PRD section 2.3) ---
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --- Shared default windows used by composite fixtures ---
DEFAULT_WINDOW_START = "2026-08-10T19:00:00Z"
DEFAULT_WINDOW_END = "2026-08-10T19:30:00Z"
DEFAULT_AUTH_WINDOW_START = "2026-08-10T18:00:00Z"
DEFAULT_AUTH_WINDOW_END = "2026-08-10T21:00:00Z"
PRE_SHOW_EVAL_CLOCK = "2026-08-10T18:45:00Z"
DEFAULT_READING_AT = "2026-08-10T18:30:00Z"
IN_WINDOW_CLOCK = "2026-08-10T19:05:00Z"

# Well-formed UUID that resolves to nothing (used for 404 sweeps).
UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"
