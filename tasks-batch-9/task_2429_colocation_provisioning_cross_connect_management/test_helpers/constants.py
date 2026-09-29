"""Numeric constants the PRD pins for the colocation calculations, plus the
pagination and clock defaults the PRD declares.
"""

# --- logical clock ---------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
"""The clock value in force when an operator has never set it."""

# --- pagination ------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- circuit derating ------------------------------------------------------

NEC_DERATE_FACTOR = 0.80
PHASE_FACTOR_SINGLE = 1.0
PHASE_FACTOR_THREE = 1.732
REDUNDANT_COOLING_FACTOR = 0.25

# --- row capacity and posture ---------------------------------------------

COOLING_ALERT_RATIO = 0.90
MEASURED_WINDOW_DAYS = 30

# --- provisioning gates ----------------------------------------------------

BREAKER_HEADROOM_RATIO = 1.25
DENSITY_TOLERANCE_RATIO = 1.10
POWER_OVERPROVISION_CAP_RATIO = 1.10
PORT_QUARANTINE_HOURS = 24
MAX_ROUTE_REVISIONS = 2

# --- power billing ---------------------------------------------------------

POWER_COMMIT_RATE_USD_PER_KW_MONTH = 175.00
COMMIT_HOURS_PER_MONTH = 730
DEEMED_LOAD_FACTOR = 0.65
OVERAGE_TIER_1_LIMIT_KWH = 500
OVERAGE_TIER_2_LIMIT_KWH = 2000
OVERAGE_TIER_1_RATE = 0.1800
OVERAGE_TIER_2_RATE = 0.1550
OVERAGE_TIER_3_RATE = 0.1350

# --- remote-hands labour ---------------------------------------------------

BILLING_INCREMENT_MINUTES = 15
REMOTE_HANDS_RATE_USD_PER_INCREMENT = 62.50
AFTER_HOURS_MULTIPLIER = 1.35
AFTER_HOURS_MORNING_HOUR = 8
AFTER_HOURS_EVENING_HOUR = 20
SLA_BREACH_CREDIT_PCT = 0.25

RESPONSE_TARGET_MINUTES = {
    "CRITICAL": 30,
    "HIGH": 120,
    "STANDARD": 480,
}

# --- cross-connect billing -------------------------------------------------

CC_MEDIA_MRC_USD = {
    "SMF": 300.00,
    "MMF": 250.00,
    "CAT6A": 175.00,
    "COAX": 225.00,
}
CC_VOLUME_TIER_1_MIN_USD = 500.00
CC_VOLUME_TIER_2_MIN_USD = 800.00
CC_VOLUME_DISCOUNT_TIER_1_PCT = 0.05
CC_VOLUME_DISCOUNT_TIER_2_PCT = 0.10
INFRA_SURCHARGE_PCT = 0.20
CC_DECOMMISSION_CREDIT_PCT = 0.50

# --- default shapes used to build test scenery ----------------------------

ROW_DEFAULTS = {
    "cabinet_slot_count": 8,
    "design_density_kw_per_cabinet": 25.0,
    "max_row_power_kw": 200.0,
    "cooling_capacity_kw": 60.0,
    "escort_slot_count": 1,
    "decommission_flag": False,
}

CONTRACT_DEFAULTS = {
    "billing_mode": "COMMITTED_ONLY",
    "committed_cabinet_count": 1,
    "power_commit_kw": 20.0,
    "committed_bandwidth_mbps": 1000,
    "cross_connect_cap": 4,
    "term_start_date": "2026-07-01T00:00:00Z",
    "term_end_date": "2027-06-30T00:00:00Z",
    "committed_cage_sqft": 0,
    "redundancy_requirement": "N",
    "cross_connect_allowance": 0,
    "remote_hands_included_minutes": 0,
}

CABINET_DEFAULTS = {
    "rated_power_kw": 20.0,
    "footprint_type": "CABINET",
    "u_height": 42,
}

CIRCUIT_DEFAULTS = {
    "feed_side": "A",
    "redundancy_role": "PRIMARY",
    "breaker_amps": 50,
    "volts": 240,
    "phase": "SINGLE",
}

KW_DECIMALS = 3
USD_DECIMALS = 2
UNIT_RATE_DECIMALS = 4
