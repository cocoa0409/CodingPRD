"""Domain constants published by the specification.

These are the numbers the API is required to use; tests reference them by name
so that an expectation reads like the rule it is checking.
"""

from __future__ import annotations

from typing import Dict

# --- performance-limited takeoff weight adjustments --------------------------
ALTITUDE_PENALTY_KG_PER_1000_FT = 220.0
TEMPERATURE_PENALTY_KG_PER_C = 130.0
WIND_CREDIT_KG_PER_KT = 90.0
MAX_WIND_CREDIT_KG = 900.0
MAX_CREDITED_HEADWIND_KT = 10.0
PERFORMANCE_ROUNDING_STEP_KG = 10

CONTAMINATION_FACTOR: Dict[str, float] = {
    "DRY": 1.00,
    "WET": 0.93,
    "CONTAMINATED": 0.85,
}

# --- last-minute change allowance -------------------------------------------
LMC_ALLOWANCE_HARD_CAP_KG = 500.0

# --- load audit severity bands ---------------------------------------------
SEVERITY_MINOR_UPPER_KG = 500.0
SEVERITY_MAJOR_UPPER_KG = 1000.0

# --- temporal rules ---------------------------------------------------------
AIRCRAFT_TURNAROUND_BUFFER_MINUTES = 45
RUNWAY_SLOT_WINDOW_MINUTES = 10

# --- pagination -------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- logical clock ----------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
SETUP_CLOCK_UTC = "2026-08-15T06:00:00Z"

# --- numeric comparison tolerance ------------------------------------------
MONEY_TOLERANCE = 0.01

# --- rounding / precision --------------------------------------------------
DECIMAL_PLACES = 2

# --- offload priority ranks (lower rank leaves first) ----------------------
OFFLOAD_RANK_COMPANY = 1
OFFLOAD_RANK_GENERAL = 2
OFFLOAD_RANK_MAIL = 3
OFFLOAD_RANK_GATE_BAG = 4
