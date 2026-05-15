"""Domain thresholds and constants from the PRD.

Numeric values used in PRD §2.7, §3.5, §3.7 calculations and test
defaults that exercise them.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Billing constants (PRD §3.7)
# ---------------------------------------------------------------------------
PER_SWAP_BASE_CENTS = 500

# Time-of-use rates in cents per kWh (PRD §3.7)
TOU_RATE_PEAK = 40
TOU_RATE_SHOULDER = 25
TOU_RATE_OFF_PEAK = 15

# Markup over raw electricity (PRD §3.7)
SOC_DIFF_MULTIPLIER = 1.20

# Per-tier subscription deduction in cents (PRD §3.7)
SUBSCRIPTION_DEDUCTION_NONE = 0
SUBSCRIPTION_DEDUCTION_BASIC = 500
SUBSCRIPTION_DEDUCTION_PREMIUM = 1500


# ---------------------------------------------------------------------------
# SOH assessment constants (PRD §3.5)
# ---------------------------------------------------------------------------
RESISTANCE_BASELINE_MOHM = 50
RESISTANCE_PENALTY_PER_MOHM = 0.10
TEMP_HIGH_C = 35
TEMP_LOW_C = 10
TEMP_PENALTY_PER_C = 0.05
CYCLE_BASELINE = 500
CYCLE_PENALTY_PER_CYCLE = 0.005

# Grading thresholds (PRD §3.5)
GRADE_A_FLOOR = 90.0
GRADE_C_FLOOR = 70.0
DEFAULT_EV_SOH_FLOOR_PCT = 80.0  # PRD §3.1 default for BatteryModel

# Cascade grading (PRD §3.5)
CASCADE_ENERGY_STORAGE_MAX_CYCLES = 1500
CASCADE_LSV_MAX_CYCLES = 2500


# ---------------------------------------------------------------------------
# Reservation / member temporal rules (PRD §3.3)
# ---------------------------------------------------------------------------
RESERVATION_SLOT_MINUTES = 15
RESERVATION_LEAD_MINUTES = 5
RESERVATION_CANCEL_LEAD_MINUTES = 5
NO_SHOW_THRESHOLD_30D = 3
NO_SHOW_BLOCK_HOURS = 72
WALK_IN_INCREMENT_MINUTES = 5


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_LIMIT = 10


# ---------------------------------------------------------------------------
# Test defaults — concrete factory values
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "STATION_NAME": "Test Station",
    "STATION_LAT": 30.0,
    "STATION_LON": 120.0,
    "STATION_TOTAL_SLOTS": 4,

    "BATTERY_MODEL_CODE_DEFAULT": "BM-A1",
    "BATTERY_MODEL_RATED_KWH": 50.0,
    "BATTERY_MODEL_NOMINAL_V": 400.0,
    "BATTERY_MODEL_MANUFACTURER": "TestMfg",

    "VEHICLE_MODEL_CODE_DEFAULT": "VM-Sedan-2024",
    "VEHICLE_MODEL_NAME": "Test Sedan",
    "VEHICLE_MODEL_VMIN": 350.0,
    "VEHICLE_MODEL_VMAX": 450.0,

    "BATTERY_SERIAL_PREFIX": "SN",
    "WARRANTY_EXPIRES_AT": "2030-01-01T00:00:00.000Z",

    "MEMBER_NAME": "Test Member",
}


__all__ = [
    "PER_SWAP_BASE_CENTS",
    "TOU_RATE_PEAK",
    "TOU_RATE_SHOULDER",
    "TOU_RATE_OFF_PEAK",
    "SOC_DIFF_MULTIPLIER",
    "SUBSCRIPTION_DEDUCTION_NONE",
    "SUBSCRIPTION_DEDUCTION_BASIC",
    "SUBSCRIPTION_DEDUCTION_PREMIUM",
    "RESISTANCE_BASELINE_MOHM",
    "RESISTANCE_PENALTY_PER_MOHM",
    "TEMP_HIGH_C",
    "TEMP_LOW_C",
    "TEMP_PENALTY_PER_C",
    "CYCLE_BASELINE",
    "CYCLE_PENALTY_PER_CYCLE",
    "GRADE_A_FLOOR",
    "GRADE_C_FLOOR",
    "DEFAULT_EV_SOH_FLOOR_PCT",
    "CASCADE_ENERGY_STORAGE_MAX_CYCLES",
    "CASCADE_LSV_MAX_CYCLES",
    "RESERVATION_SLOT_MINUTES",
    "RESERVATION_LEAD_MINUTES",
    "RESERVATION_CANCEL_LEAD_MINUTES",
    "NO_SHOW_THRESHOLD_30D",
    "NO_SHOW_BLOCK_HOURS",
    "WALK_IN_INCREMENT_MINUTES",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_LIMIT",
    "TEST_DEFAULTS",
]
