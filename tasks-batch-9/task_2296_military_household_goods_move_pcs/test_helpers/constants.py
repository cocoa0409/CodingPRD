"""Numeric thresholds and rate tables published by the PRD."""

# --- Logical clock -----------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
# Every scenario pins the clock before building state so date arithmetic is stable.
BASE_CLOCK_UTC = "2026-08-03T00:00:00Z"

# --- Weight allowance table (base_weight_allowance_lbs) ----------------------
# rank_code -> (WITHOUT_DEPENDENTS, WITH_DEPENDENTS)

WEIGHT_ALLOWANCE_TABLE = {
    "E1": (5000, 8000),
    "E2": (5000, 8000),
    "E3": (5000, 8000),
    "E4": (5000, 8000),
    "E5": (7000, 9000),
    "E6": (8000, 11000),
    "E7": (11000, 13000),
    "E8": (12000, 14000),
    "E9": (13000, 15000),
    "W1": (10000, 12000),
    "W2": (12500, 13500),
    "W3": (13000, 14500),
    "W4": (14000, 17000),
    "W5": (16000, 17500),
    "O1": (10000, 12000),
    "O2": (12500, 13500),
    "O3": (13000, 14500),
    "O4": (14000, 17000),
    "O5": (16000, 17500),
    "O6": (18000, 18000),
}

SEPARATION_RETIREMENT_CAP_LBS = 13000
PRO_GEAR_MEMBER_ALLOWANCE_LBS = 2000
PRO_GEAR_SPOUSE_ALLOWANCE_LBS = 500
PRO_GEAR_MAX_CLAIMED_WEIGHT_LBS = 2500
PRO_GEAR_RESUBMISSION_LIMIT = 2
ADMIN_WEIGHT_BUMP_MAX_LBS = 2000

# --- Counseling --------------------------------------------------------------

COUNSELING_DEADLINE_LEAD_DAYS = 14

# --- Excess weight cost ------------------------------------------------------

EXCESS_RATE_TIERS = {
    "LOW": 62.50,      # excess_pct_over <= 0.10
    "MEDIUM": 78.00,   # 0.10 < excess_pct_over <= 0.25
    "HIGH": 94.50,     # excess_pct_over > 0.25
}
EXCESS_RATE_TIER_LOW_MAX_PCT = 0.10
EXCESS_RATE_TIER_MEDIUM_MAX_PCT = 0.25
ADMIN_FEE_THRESHOLD_USD = 500.00
ADMIN_FEE_PCT = 0.06
SUSPENSION_THRESHOLD_USD = 2500.00

# --- Capacity blocks ---------------------------------------------------------

PEAK_SEASON_RESERVE_FLOOR_PCT = 0.25
CAPACITY_RESTRICTED_UTILISATION_PCT = 0.90
CAPACITY_WEEK_LENGTH_DAYS = 7

# --- Spread window and transit ----------------------------------------------

SHORT_NOTICE_THRESHOLD_DAYS = 5
SPREAD_SHORT_NOTICE = (0, 2)
SPREAD_PEAK = (2, 7)
SPREAD_STANDARD = (1, 4)
TRANSIT_MIN_DAYS = 5
TRANSIT_MILES_PER_DAY = 300
TRANSIT_PEAK_EXTRA_DAYS = 2

# --- Survey ------------------------------------------------------------------

CUBE_TO_POUNDS_FACTOR = 7
SURVEY_UPLIFT_PCT = 0.05

# --- Reweigh trigger ---------------------------------------------------------

REWEIGH_TOLERANCE_MULTIPLIER = 1.10

# --- Storage in transit ------------------------------------------------------

SIT_MAX_DAYS = 90
SIT_HANDLING_PER_CWT_USD = 68.40
SIT_TIER1_PER_CWT_PER_DAY_USD = 1.05
SIT_TIER1_DAY_LIMIT = 30
SIT_EXTENDED_PER_CWT_PER_DAY_USD = 1.62
SIT_FUEL_SURCHARGE_TIERS = {
    "LOW": 0.045,     # sit_base_cost_usd < 1000.00
    "MEDIUM": 0.062,  # 1000.00 <= sit_base_cost_usd < 5000.00
    "HIGH": 0.071,    # sit_base_cost_usd >= 5000.00
}
SIT_FUEL_TIER_LOW_MAX_USD = 1000.00
SIT_FUEL_TIER_MEDIUM_MAX_USD = 5000.00

# --- Weight dispute ----------------------------------------------------------

WEIGHT_DISPUTE_WINDOW_DAYS = 45

# --- Personally procured moves ----------------------------------------------

PPM_GCC_BASE_PER_CWT_USD = 42.75
PPM_GCC_PER_CWT_PER_HUNDRED_MILES_USD = 3.85
PPM_INCENTIVE_PCT = 0.95

# --- Claims ------------------------------------------------------------------

CLAIM_NOTICE_WINDOW_DAYS = 180
CLAIM_FILING_WINDOW_DAYS = 730
CLAIM_FULL_REPLACEMENT_WINDOW_DAYS = 270
CLAIM_SETTLEMENT_CAP_USD = 100000.00
CLAIM_UNDOCUMENTED_ITEM_CAP_USD = 5000.00
CLAIM_INFO_REQUEST_LIMIT = 3
DEPRECIATION_RATES = {
    "ELECTRONICS": 0.10,
    "FURNITURE": 0.05,
    "APPLIANCE": 0.07,
    "CLOTHING": 0.20,
    "OTHER": 0.06,
}
DEPRECIATION_RESIDUAL_FLOOR = 0.20
CLAIM_ITEM_MAX_AGE_YEARS = 60.0

# --- Provider performance ----------------------------------------------------

PERFORMANCE_START_SCORE = 100.00
PERFORMANCE_PENALTY_PER_SETTLED_CLAIM = 5
PERFORMANCE_SETTLEMENT_DIVISOR = 500
PERFORMANCE_SUSPENDED_BELOW = 50
PERFORMANCE_PROBATION_BELOW = 70

# --- Notification service levels --------------------------------------------

SLA_HOURS = {
    "PACK_DATE_CONFIRMED": 72,
    "PICKUP_CONFIRMED": 24,
    "SIT_ENTRY": 24,
    "WEIGHT_RECON_COMPLETE": 168,
    "CLAIM_ACK": 120,
}

# --- Orders ------------------------------------------------------------------

ORDER_AMENDMENT_LIMIT = 3
ORDER_MAX_DISTANCE_MILES = 12000
MAX_DEPENDENTS_COUNT = 12

# --- Pagination --------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
