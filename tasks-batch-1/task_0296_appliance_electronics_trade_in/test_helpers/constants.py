"""Domain thresholds and canonical fixture constants from the PRD pricing model.

These mirror the canonical Catalog / DeviceModel used throughout the test suite:
a SMARTPHONE model "PHN-1" with base_value_cents 60000, the standard condition
multipliers and defect deductions, under a Catalog with price_lock_hours 168,
requote_tolerance_pct 0.15, recycle_floor_value_cents 5000.

All money values are integer cents (PRD §2.8).
"""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

# Catalog policy knobs (PRD §3.1)
DEFAULT_PRICE_LOCK_HOURS = 168
DEFAULT_REQUOTE_TOLERANCE_PCT = 0.15
DEFAULT_RECYCLE_FLOOR_CENTS = 5000

# Canonical device model pricing inputs (PRD §3.1 / §3.4)
BASE_VALUE_CENTS = 60000

CONDITION_MULTIPLIERS = {
    "FLAWLESS": 1.0,
    "GOOD": 0.8,
    "FAIR": 0.6,
    "POOR": 0.35,
}

DEFECT_DEDUCTIONS = {
    "CRACKED_SCREEN": 12000,
    "BATTERY_DEGRADED": 4000,
    "WATER_DAMAGE": 20000,
    "MISSING_PARTS": 5000,
    "WONT_POWER_ON": 15000,
    "DENTED_BODY": 3000,
}

# Derived graded values worked by the PRD §3.4 formula (round_half_up, integer cents)
# under the canonical model above:
#   GOOD,[],on                 -> 48000
#   GOOD,[CRACKED_SCREEN],on   -> 36000
#   FAIR,[WATER_DAMAGE],on     -> 16000
#   FLAWLESS,[],on             -> 60000
#   FLAWLESS,[BATTERY_DEGRADED,MISSING_PARTS],on             -> 51000
#   FLAWLESS,[BATTERY_DEGRADED,MISSING_PARTS,DENTED_BODY],on -> 48000
#   GOOD,[],off (POOR floor 21000 - WONT_POWER_ON 15000)     -> 6000
#   POOR,[WATER_DAMAGE],off (21000 - 20000 - 15000 floored)  -> 0
GRADED_GOOD_NO_DEFECT = 48000
GRADED_GOOD_CRACKED = 36000
GRADED_FAIR_WATER = 16000
GRADED_FLAWLESS = 60000

# A fixed clock instant inside the canonical promo windows for deterministic tests.
CLOCK_WITHIN_2026 = "2026-06-01T00:00:00Z"
