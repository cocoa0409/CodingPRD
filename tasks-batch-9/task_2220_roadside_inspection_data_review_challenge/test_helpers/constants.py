"""Domain constants published by the PRD for the roadside inspection data review API.

Every value here is quoted from the PRD so tests never re-derive a threshold by
hand.  Section references in the comments point at the PRD section that fixes
the value.
"""

# --- PRD 2.4 logical clock -------------------------------------------------
#: The server's logical clock starts here and never falls back to wall-clock time.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- PRD 2.3 pagination ---------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- PRD 3.3 severity pin: time-weight decay bands -----------------------
WEIGHT_3_MAX_AGE_DAYS = 182
WEIGHT_2_MAX_AGE_DAYS = 365
WEIGHT_1_MAX_AGE_DAYS = 730
TIME_WEIGHT_RECENT = 3
TIME_WEIGHT_MID = 2
TIME_WEIGHT_OLD = 1
TIME_WEIGHT_EXPIRED = 0

# --- PRD 3.4 measure recompute ------------------------------------------
LOOKBACK_DAYS = 730
UTILIZATION_TIER_1_MAX_VMT_PER_PU = 20000
UTILIZATION_TIER_2_MAX_VMT_PER_PU = 60000
UTILIZATION_TIER_3_MAX_VMT_PER_PU = 100000
UTILIZATION_FACTORS = {
    "TIER_1": 1.0,
    "TIER_2": 1.2,
    "TIER_3": 1.5,
    "TIER_4": 1.8,
}
HOS_INSPECTION_MULTIPLIER = 2.0

#: PRD 3.1 fleet-size bands.
SEGMENT_SMALL_MAX_POWER_UNITS = 15
SEGMENT_MEDIUM_MAX_POWER_UNITS = 100

# --- PRD 3.4 intervention posture ---------------------------------------
INVESTIGATION_ALERT_COUNT = 2
DEFAULT_MONITOR_PERCENTILE = 50.0
DEFAULT_INTERVENTION_PERCENTILE = 65.0
DEFAULT_INVESTIGATION_PERCENTILE = 85.0

# --- PRD 3.5 screening risk ---------------------------------------------
CATEGORY_WEIGHT = {
    "UNSAFE_DRIVING": 0.35,
    "HOURS_OF_SERVICE": 0.30,
    "VEHICLE_MAINTENANCE": 0.25,
    "DRIVER_FITNESS": 0.10,
}
OOS_ADDER_PER_VIOLATION = 0.5
OOS_ADDER_CAP = 10.0
BAND_INSPECT_MIN = 75.0
BAND_OPTIONAL_MIN = 50.0
CREDIT_TIER_HIGH = 0.06       # iss_pre_credit_value >= 75.0
CREDIT_TIER_MID = 0.04        # iss_pre_credit_value >= 50.0
CREDIT_TIER_LOW = 0.02        # otherwise

# --- PRD 3.9 driver attribution -----------------------------------------
COACHING_TRIGGER = 12.0
SEVERITY_FACTOR_DISMISSED = 0.0
SEVERITY_FACTOR_REDUCED = 0.5
SEVERITY_FACTOR_DEFAULT = 1.0

# --- PRD 3.6 challenge quota ledger -------------------------------------
QUOTA_WINDOW_DAYS = 30
QUOTA_LIMIT_SMALL = 1
QUOTA_LIMIT_MEDIUM = 3
QUOTA_LIMIT_LARGE = 6
MAX_INFO_ROUNDS = 3
CHALLENGE_FILING_WINDOW_DAYS = 730

# --- PRD 3.2 duplicate inspection window --------------------------------
DUPLICATE_BUFFER_MINUTES = 120

# --- PRD 3.10 CAP rollup ------------------------------------------------
JOIN_COMPLETION_PCT = 100.0

# --- Rounding tolerances (PRD 2.7) --------------------------------------
#: measures carry three decimals
MEASURE_TOLERANCE = 0.0005
#: percentiles, iss values and completion percentages carry one decimal
ONE_DECIMAL_TOLERANCE = 0.005
#: contributions and attribution scores carry two decimals
TWO_DECIMAL_TOLERANCE = 0.005
#: data-quality credit carries four decimals
CREDIT_TOLERANCE = 0.00005

# --- Convenient test defaults -------------------------------------------
TEST_DEFAULTS = {
    # A 20-power-unit / 1,600,000 VMT carrier is MEDIUM with
    # vmt_per_pu 80,000 -> utilization_factor 1.5 -> exposure 30.0.
    "medium_carrier_power_units": 20,
    "medium_carrier_annual_vmt": 1600000,
    # A 10-power-unit / 1,200,000 VMT carrier is SMALL with
    # vmt_per_pu 120,000 -> utilization_factor 1.8 -> exposure 18.0.
    "small_carrier_power_units": 10,
    "small_carrier_annual_vmt": 1200000,
    "threshold_effective_from": "2026-01-01T00:00:00Z",
    "inspection_start": "2026-07-01T14:00:00Z",
    "inspection_end": "2026-07-01T15:00:00Z",
}

BASIC_CATEGORIES = (
    "UNSAFE_DRIVING",
    "HOURS_OF_SERVICE",
    "VEHICLE_MAINTENANCE",
    "DRIVER_FITNESS",
)
