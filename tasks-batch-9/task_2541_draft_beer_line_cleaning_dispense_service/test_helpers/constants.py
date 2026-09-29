"""Domain constants, thresholds and derived-value tables from PRD.md.

Only values the PRD states in prose appear here.  Tests import these instead of
re-typing magic numbers so that a single reading of the contract is shared by
every assertion.
"""

# --- Service root -----------------------------------------------------------
API_ROOT = "/draft-service"

# --- Logical service clock --------------------------------------------------
#: The value every clock read returns before the clock has ever been set.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination -------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Cleaning cadence -------------------------------------------------------
ALLOWED_CLEANING_FREQUENCY_DAYS = (14, 21, 28)
#: cleaning_frequency_days -> frequency_multiplier
FREQUENCY_MULTIPLIER = {14: 1.00, 21: 1.10, 28: 1.25}
#: Days a line may run past next_due_at and still read COMPLIANT.
GRACE_DAYS = 3
#: A cycle may be pulled forward at most this many days ahead of next_due_at.
EARLY_WINDOW_DAYS = 2

# --- Route board ------------------------------------------------------------
MAX_LEAD_DAYS = 45
TRAVEL_BUFFER_MINUTES = 30

# --- Chemistry / dosing -----------------------------------------------------
#: inner_diameter_inches -> litres of beer held per foot of run.
LITERS_PER_FOOT = {0.1875: 0.0173, 0.25: 0.0308, 0.375: 0.0692}
FLUSH_FACTOR = 3.0
MIN_SOLUTION_LITERS = 4
MIN_USABLE_LITERS = 0.05
#: chemical_type -> target solution strength in percent.
TARGET_ACTIVE_PCT = {"CAUSTIC": 2.0, "ACID": 1.0}
#: chemical_type -> minimum recirculation temperature in Fahrenheit.
MIN_RECIRC_TEMP_F = {"CAUSTIC": 95.0, "ACID": 70.0}
#: chemical_type -> minimum achieved strength in percent.
MIN_EFFECTIVE_PCT = {"CAUSTIC": 1.5, "ACID": 0.75}
#: Achieved-strength tiers, highest first: (minimum pct, required contact minutes).
CAUSTIC_CONTACT_TIERS = ((2.0, 15), (1.5, 20), (0.0, 30))
ACID_CONTACT_TIERS = ((1.0, 10), (0.75, 15), (0.0, 25))

# --- Gas blend and pressure balancing ---------------------------------------
CO2_BASE_VOLUMES = 1.2
VOL_TO_PSI = 5.5
TEMP_REF_F = 38.0
TEMP_PSI_SLOPE = 0.45
RISE_PSI_PER_FOOT = 0.5
FAUCET_LOSS_PSI = 2.0
BALANCE_TOLERANCE_PSI = 0.75
APPLIED_PSI_TOLERANCE = 0.5
CO2_PCT_TOLERANCE = 2.0
NITRO_TARGET_CO2_VOLUMES = 1.2
NITRO_REQUIRED_CO2_PCT = 25.0
MIN_REQUIRED_CO2_PCT = 40.0
MAX_REQUIRED_CO2_PCT = 100.0
COLD_BAND_MAX_F = 38.0
MILD_BAND_MAX_F = 42.0
#: inner_diameter_inches -> restriction psi per foot of run.
RESTRICTION_PSI_PER_FOOT = {0.1875: 2.2, 0.25: 0.85, 0.375: 0.30}
#: beer_style_group -> (cold, mild, warm) target carbonation volumes.
TARGET_CO2_VOLUMES = {
    "ALE": (2.4, 2.5, 2.6),
    "LAGER": (2.6, 2.7, 2.8),
    "CIDER": (2.8, 2.9, 3.0),
}

# --- Money ------------------------------------------------------------------
WAIVER_WITHHOLD_BPS = 1000
BPS_DENOMINATOR = 10000
WHOLESALE_CENTS_PER_LITER = 480

# --- Verification windows ---------------------------------------------------
DISPUTE_WINDOW_HOURS = 168
WAIVER_WAIT_HOURS = 72

# --- Complaints -------------------------------------------------------------
MAX_DAYS_AT_RISK = 30
MAX_DIAGNOSTIC_ROUNDS = 3
REOPEN_WINDOW_HOURS = 336
REOPEN_LIMIT = 2
FOAM_ALLOWANCE_LITERS_PER_DAY = 0.5
#: symptom -> severity factor.
SEVERITY_FACTOR = {
    "FOAMY_POUR": 0.35,
    "FLAT_POUR": 0.20,
    "OFF_FLAVOR": 0.50,
    "SLOW_POUR": 0.15,
    "CLOUDY": 0.30,
}

# --- Glycol health ----------------------------------------------------------
READING_WINDOW = 3
TARGET_COOLER_TEMP_F = 38.0
TEMP_PENALTY_PER_DEGREE = 8.0
MIN_GLYCOL_PCT = 30.0
GLYCOL_PENALTY_PER_PCT = 2.5
MIN_PUMP_PSI = 9.0
PUMP_PENALTY_FLAT = 12.0
GLYCOL_SERVICE_INTERVAL_DAYS = 180
SERVICE_PENALTY_PER_DAY = 0.6
WATCH_THRESHOLD = 75.0
ALARM_THRESHOLD = 50.0

# --- Cascade-created glycol loop seed values --------------------------------
SEED_GLYCOL_PCT = 35.0
SEED_PUMP_PSI = 12.0
SEED_BATH_TEMP_F = 28.0
SEED_HEALTH_SCORE = 100.0
