"""Domain thresholds — numeric constants from PRD calculations (PRD §2.6, §3.2-§3.8)."""

# --- quote_total (PRD §3.3, §3.4) ---
TAX_RATE = 0.08

# --- winter_risk_score (PRD §3.8) ---
PLANT_WEIGHT = {"TURF": 4, "ROTOR": 3, "SHRUB": 2, "DRIP": 1}
HIGH_PSI = 80
RISK_CAP = 1000

# --- blowout_price (PRD §3.8) ---
BASE_FEE_CENTS = 4500
TIER1_RATE_CENTS = 1200       # zone_count <= 4
TIER2_RATE_CENTS = 1000       # 5 <= zone_count <= 10
TIER3_RATE_CENTS = 850        # zone_count >= 11
PSI_SURCHARGE_PER_PSI = 50
PSI_SURCHARGE_CAP_CENTS = 3000

# --- plan_annual_dues (PRD §3.7) ---
TIER_RATE_BASIC_CENTS = 6000
TIER_RATE_PLUS_CENTS = 9000
TIER_RATE_PREMIUM_CENTS = 13000
LOYALTY_LO_CENTS = 60000      # >= 60000 -> 8%
LOYALTY_HI_CENTS = 120000     # >= 120000 -> 15%

# --- backflow_result (PRD §3.5) ---
MIN_RELIEF_PSI = 2
MIN_HOLD_PSI = 1

# --- program_slot_overlap_check (PRD §3.2) ---
VALVE_SWITCH_BUFFER_SEC = 120

# --- route_capacity_check (PRD §3.6) ---
MAX_STOPS_PER_ROUTE = 8

# Generic test defaults
TEST_DEFAULTS = {
    "static_psi": 60,
    "controller_model": "Hunter",
    "shift_start_sec": 28800,   # 08:00
    "shift_end_sec": 64800,     # 18:00 -> 600 minute shift
}
