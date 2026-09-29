"""Domain thresholds — every numeric constant the PRD pins by name.

Values are copied from the PRD prose in §2.6 through §3.9; nothing here is
inferred.
"""

# --- The logical clock (PRD §2.6) -----------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- Permit classing and escort sizing (PRD §3.4) -------------------------
OVERSIZE_WIDTH_IN = 192
SUPERLOAD_WIDTH_IN = 216
OVERHEIGHT_IN = 162
MAX_ESCORTS = 4
NIGHT_MOVE_ESCORT_BONUS = 1
PILOT_CAR_LEG_THRESHOLD = 3
STATE_ESCORT_BASE = {"AZ": 0, "NM": 1, "TX": 1, "OK": 1, "KS": 2, "CO": 2}

# --- Permit fee assessment (PRD §3.4) ------------------------------------
BASE_FEE_CENTS = 12_000
WIDTH_FREE_ALLOWANCE_IN = 168
PER_INCH_OVER_WIDTH_CENTS = 250
PER_LEG_CENTS = 4_500
ESCORT_SURCHARGE_CENTS = 7_500
OVERHEIGHT_SURCHARGE_CENTS = 9_000
SUPERLOAD_MULTIPLIER = 1.25
PERMIT_VALID_DAYS = 5

# --- Site readiness (PRD §3.3) -------------------------------------------
MIN_PIERS_PER_SECTION = 6
MAX_BLOCKING_DEFECTS = 3

# --- Marriage line closure (PRD §3.7) ------------------------------------
MAX_GAP_IN = 0.25
MAX_OFFSET_IN = 0.5
GAP_WEIGHT = 1.0
OFFSET_WEIGHT = 0.6
SHIM_WEIGHT = 0.4
CLOSURE_PASS_MAX_SCORE = 1.00

# --- Scope split, crossover and invoice (PRD §3.7, §3.8) -----------------
SKIRTING_RATE_CENTS_PER_FT = 1_850
STEPS_UNIT_CENTS = 42_000
UTILITY_CROSSOVER_BASE_CENTS = 60_000
PER_CROSSOVER_CENTS = 18_000
TIER_3_MIN_CENTS = 300_000
TIER_6_MIN_CENTS = 600_000
TIER_10_MIN_CENTS = 900_000
TIER_3_PCT = 0.03
TIER_6_PCT = 0.06
TIER_10_PCT = 0.10

# --- Anchoring certification (PRD §3.8) ---------------------------------
MIN_TORQUE_FT_LB = 175
REQUIRED_STRAPS_PER_ANCHOR = 1
REQUIRED_ANCHORS_PER_ZONE = {"I": 8, "II": 12, "III": 16}
STATE_EXTRA_ANCHORS = 4
STATE_EXTRA_ANCHOR_STATES = ["KS", "CO"]
MAX_ANCHOR_REVISIONS = 3

# --- Damage claims and the chargeback ledger (PRD §3.9, §3.1) -----------
APPROVAL_HAIRCUT_PCT = 0.10
CLAIM_CAP_CENTS = 2_500_000
HAULER_SUSPENSION_THRESHOLD_CENTS = 500_000
PLANT_PROBATION_THRESHOLD_CENTS = 750_000
EVIDENCE_TIE_ORDER = ["HAULER", "INSTALLER", "PLANT"]
STAGE_OWNER = {
    "PLANT_QC": "PLANT",
    "IN_TRANSIT": "HAULER",
    "AT_SET": "INSTALLER",
    "FINAL_INSPECTION": "INSTALLER",
}

# --- Escort crew scheduling defaults (PRD §3.1) -------------------------
DEFAULT_BUFFER_MINUTES = 45
DEFAULT_MAX_RESERVED_MINUTES = 600
DEFAULT_DAILY_CAPACITY = 1

# --- Pagination (PRD §2.3) ----------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
