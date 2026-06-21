"""Domain thresholds — numeric constants from PRD calculations (Sections 3.9-3.14).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# --- Cost rates (PRD 3.9 / 3.12) ---
OR_MINUTE_RATE_CENTS = 1200            # $12.00 per scheduled/actual minute
ANESTHESIA_BASE_CENTS = {
    "LOCAL": 0,
    "MAC": 18000,
    "REGIONAL": 32000,
    "GENERAL": 55000,
}
ADD_ON_SURCHARGE_CENTS = 40000         # $400 flat add-on surcharge

# --- Over-run tiered penalty (PRD 3.12) ---
OVERRUN_TIER1_MIN = 15                 # band 1 covers over-run minutes 1..15
OVERRUN_TIER2_MIN = 45                 # band 2 covers minutes 16..45 (cumulative breakpoint)
OVERRUN_TIER1_RATE_CENTS = 800         # $8.00/min for band 1
OVERRUN_TIER2_RATE_CENTS = 1500        # $15.00/min for band 2
OVERRUN_TIER3_RATE_CENTS = 3000        # $30.00/min beyond 45

# --- ASC payment grouping (PRD 3.13) ---
MULTI_PROC_REDUCTION_PCT = 50          # 50% reduction on 2nd+ procedure same patient/day
OFFICE_BASED_FLOOR_CENTS = 9000        # office-based floor

# --- Anesthesia coverage load (PRD 3.14) ---
SOLO_COVERAGE_CAP_MIN = 480            # 8 prime-time hours of solo coverage

# --- Facility / scheduling defaults (PRD 3.1 / 3.3) ---
DEFAULT_TURNOVER_MINUTES = 25
DEFAULT_HP_VALIDITY_DAYS = 30
DEFAULT_UTILIZATION_TARGET_PCT = 75
DEFAULT_PRIME_TIME_START_MIN = 420     # 07:00
DEFAULT_PRIME_TIME_END_MIN = 960       # 16:00
DEFAULT_RELEASE_THRESHOLD_HOURS = 48
EPOCH_UTC = "1970-01-01T00:00:00.000Z"
