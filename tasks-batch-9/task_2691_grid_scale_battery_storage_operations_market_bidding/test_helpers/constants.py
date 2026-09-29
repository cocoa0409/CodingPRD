"""Domain thresholds and pinned numeric constants drawn from the PRD."""

# --- Offer pricing (PRD 3.3) -------------------------------------------------
CHARGE_ENERGY_COST_USD_PER_MWH = 22.00
WARRANTY_ADDER_BASE_USD = 8.00
WARRANTY_ADDER_KNEE = 0.5
MIN_OFFER_PRICE_USD = 0.00
MAX_BID_REVISIONS = 3

SCARCITY_MULTIPLIERS = {
    "AT_LEAST_200": 1.00,
    "AT_LEAST_100": 1.25,
    "AT_LEAST_25": 1.60,
    "BELOW_25": 2.50,
}

PRODUCT_WEIGHTS = {
    "ENERGY": 1.00,
    "REG_UP": 0.70,
    "SPIN": 0.55,
    "REG_DOWN": 0.35,
}

# --- Dispatch performance scoring (PRD 3.5, 3.6) ----------------------------
DEADBAND_RATIO = 0.02
ACCURACY_WEIGHT = 0.7
DEADBAND_WEIGHT = 0.3
PERFORMANCE_FLOOR_SCORE = 75.00
NON_PERFORMANCE_RATE_USD = 4.00
SAMPLE_INTERVAL_HOURS = 0.25

# --- Interconnection and thermal bands (PRD 3.5) ----------------------------
THERMAL_WARNING_TEMP_C = 65.0
THERMAL_RUNAWAY_TEMP_C = 75.0

# --- Capacity obligation assessment (PRD 3.8) -------------------------------
ANNUAL_HOURS = 8760.0
AVAILABILITY_TIER1_PCT = 90.0
AVAILABILITY_TIER2_PCT = 80.0

# --- Degradation model, warranty claims and remedies (PRD 3.9) --------------
THROUGHPUT_FADE_PCT = 8.0
CLAIM_TRIGGER_DEFICIT_PCT = 1.00
REMEDY_OVERSIZE_FACTOR = 1.10
CLAIM_FILING_WINDOW_DAYS = 30
REMEDY_OUTAGE_BUFFER_DAYS = 2

# --- Logical clock (PRD 2.8) ------------------------------------------------
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# --- Ramp buffer on offer window exclusivity (PRD 3.4) ----------------------
BID_WINDOW_BUFFER_MINUTES = 15

# --- Pagination (PRD 2.3) ---------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
