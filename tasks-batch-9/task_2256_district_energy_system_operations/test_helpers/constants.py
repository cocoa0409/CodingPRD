"""Fixed constants declared by the District Energy PRD.

Every one of these is pinned by the specification text, not chosen by the
tests. Tests import them so an expected value never hard-codes a magic number
that the PRD states symbolically.
"""

API_PREFIX = "/district-energy"

# The clock endpoint is mounted at the server root rather than under the
# /district-energy prefix.
CLOCK_PATH = "/_clock/set_current_utc"

# The logical clock's startup value is exactly 2026-08-01T00:00:00Z.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ─── §2.3 Pagination ────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── §3.3 Forecast projection ───────────────────────────────────────────────
OCCUPANCY_FACTOR = {
    "WEEKDAY_FULL": 1.00,
    "WEEKEND_REDUCED": 0.72,
    "HOLIDAY_MINIMAL": 0.45,
}
CLASS_DIVERSITY_FACTOR = {
    "RESIDENTIAL_MULTIFAMILY": 0.62,
    "COMMERCIAL_OFFICE": 0.78,
    "HOSPITAL": 0.90,
    "UNIVERSITY": 0.70,
    "INDUSTRIAL_PROCESS": 0.95,
}
HDH_KW_PER_DEGREE_HOUR = 3.5
CDH_KW_PER_DEGREE_HOUR = 2.8
ACTUAL_WEIGHT = 0.70
NORMAL_WEIGHT = 0.30
DISTRIBUTION_LOSS_FACTOR = 0.08
LOSS_UPLIFT = 1.08
DISPATCH_BLOCK_HOURS = 24.0
FORECAST_LOAD_FACTOR = 0.62

# ─── §3.4 Merit order and resilience gates ──────────────────────────────────
STORAGE_DISCHARGE_HOURS = 4.0
MIN_RESERVE_MARGIN_PCT = 15.00
MAX_FUEL_DIVERSITY_HHI = 0.55
STORAGE_FUEL_KEY = "STORAGE"

# ─── §3.5 Capacity reservation ──────────────────────────────────────────────
OVERSUBSCRIPTION_FACTOR = 1.15

# ─── §3.7 Billing determinants and the arrears ledger ───────────────────────
RESERVED_FLOOR_PCT = 0.50
ARREARS_THRESHOLD_AMOUNT = 25000.00
DEFAULT_RATCHET_LOOKBACK_MONTHS = 11

# ─── §3.8 Leak risk score ───────────────────────────────────────────────────
W_AGE = 0.35
W_MAKEUP = 0.30
W_HIST = 0.20
W_INSUL = 0.15
AGE_FULL_YEARS = 60
MAKEUP_FULL_RATIO = 0.05
HIST_FULL_COUNT = 3
INSULATION_PENALTY = {"A": 0.10, "B": 0.45, "C": 0.85}
MONITORED_SCORE_FLOOR = 45.0
SUSPECT_SCORE_FLOOR = 70.0
REFILL_BUFFER_HOURS = 6

# ─── §3.9 Expansion sizing, economics and climate reporting ─────────────────
FLOW_COEFF_KW_PER_M3H_K = 1.163
PI = 3.14159265
FRICTION_COEFF = 0.01
STANDARD_DIAMETERS_MM = (80, 100, 125, 150, 200, 250, 300, 400)
MAX_VELOCITY_M_S = 2.0
MAX_PRESSURE_DROP_KPA_PER_KM = 100.0
COST_PER_MM_PER_M = 9.5
CONNECTION_FIXED_CAPEX = 85000.00
ANNUAL_OPEX_RATE = 0.025
MONTHS_PER_YEAR = 12
PV_ANNUITY_FACTOR_20Y_6PCT = 11.46992122
DELIVERED_ENERGY_FACTOR = 0.92
CITY_TARGET_KG_PER_MWH = 150.0

# Money / kW / percentage tolerance for float comparisons (2 decimal places).
MONEY_TOLERANCE = 0.01
# Energy in MWh and volumetric flow are carried to 3 decimal places.
ENERGY_TOLERANCE = 0.001
# The fuel concentration index is carried to 4 decimal places.
HHI_TOLERANCE = 0.0001

__all__ = [
    "API_PREFIX",
    "CLOCK_PATH",
    "CLOCK_STARTUP_UTC",
    "DEFAULT_LIMIT",
    "MIN_LIMIT",
    "MAX_LIMIT",
    "DEFAULT_OFFSET",
    "OCCUPANCY_FACTOR",
    "CLASS_DIVERSITY_FACTOR",
    "HDH_KW_PER_DEGREE_HOUR",
    "CDH_KW_PER_DEGREE_HOUR",
    "ACTUAL_WEIGHT",
    "NORMAL_WEIGHT",
    "DISTRIBUTION_LOSS_FACTOR",
    "LOSS_UPLIFT",
    "DISPATCH_BLOCK_HOURS",
    "FORECAST_LOAD_FACTOR",
    "STORAGE_DISCHARGE_HOURS",
    "MIN_RESERVE_MARGIN_PCT",
    "MAX_FUEL_DIVERSITY_HHI",
    "STORAGE_FUEL_KEY",
    "OVERSUBSCRIPTION_FACTOR",
    "RESERVED_FLOOR_PCT",
    "ARREARS_THRESHOLD_AMOUNT",
    "DEFAULT_RATCHET_LOOKBACK_MONTHS",
    "W_AGE",
    "W_MAKEUP",
    "W_HIST",
    "W_INSUL",
    "AGE_FULL_YEARS",
    "MAKEUP_FULL_RATIO",
    "HIST_FULL_COUNT",
    "INSULATION_PENALTY",
    "MONITORED_SCORE_FLOOR",
    "SUSPECT_SCORE_FLOOR",
    "REFILL_BUFFER_HOURS",
    "FLOW_COEFF_KW_PER_M3H_K",
    "PI",
    "FRICTION_COEFF",
    "STANDARD_DIAMETERS_MM",
    "MAX_VELOCITY_M_S",
    "MAX_PRESSURE_DROP_KPA_PER_KM",
    "COST_PER_MM_PER_M",
    "CONNECTION_FIXED_CAPEX",
    "ANNUAL_OPEX_RATE",
    "MONTHS_PER_YEAR",
    "PV_ANNUITY_FACTOR_20Y_6PCT",
    "DELIVERED_ENERGY_FACTOR",
    "CITY_TARGET_KG_PER_MWH",
    "MONEY_TOLERANCE",
    "ENERGY_TOLERANCE",
    "HHI_TOLERANCE",
]
