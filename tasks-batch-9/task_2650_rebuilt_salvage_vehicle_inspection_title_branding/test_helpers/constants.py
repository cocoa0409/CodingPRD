"""Domain thresholds and pinned numeric constants for the rebuilt-salvage program.

Every value here is quoted from the PRD's calculation and validation prose so that
tests never hard-code a magic number inline.
"""

# --- logical clock ---------------------------------------------------------
# The program clock is a logical clock seeded at a fixed instant and moved only
# by the clock control endpoint.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- damage threshold evaluation -------------------------------------------
SALVAGE_RATIO_THRESHOLD = 0.75
NON_REPAIRABLE_RATIO_THRESHOLD = 1.20
FLOOD_DEPTH_BRAND_CM = 46

# --- brand severity ladder -------------------------------------------------
BRAND_SEVERITY = {
    "NONE": 0,
    "SALVAGE": 30,
    "REBUILT": 40,
    "FLOOD": 50,
    "NON_REPAIRABLE": 90,
}

# --- record-keeping score --------------------------------------------------
ROLLING_WINDOW_DAYS = 365
TRACEABLE_POINTS = 100
UNTRACEABLE_POINTS = 40
REINSTATE_SCORE_THRESHOLD = 60.00
REVOKE_SCORE_CEILING = 40.00
EMPTY_SCORE = 100.00

# --- inspection fee assessment ---------------------------------------------
BASE_APPLICATION_FEE_CENTS = 7500
DONOR_PART_SURCHARGE_RATE = 0.015
STRUCTURAL_SURCHARGE_CENTS = 12500
SURCHARGE_CAP_CENTS = 45000

# --- total program charge --------------------------------------------------
REINSPECTION_FEE_CENTS = 4000
EXPEDITE_TIER_1_CEILING = 10000
EXPEDITE_TIER_2_CEILING = 25000
EXPEDITE_TIER_1_PCT = 0.10
EXPEDITE_TIER_2_PCT = 0.07
EXPEDITE_TIER_3_PCT = 0.05
VOLUME_DISCOUNT_PCT = 0.05
VOLUME_DISCOUNT_MIN_TITLES = 5

# --- structural adequacy score ---------------------------------------------
CHECKPOINT_WEIGHTS = {
    "STRUCTURAL_FRAME": 35,
    "RESTRAINT_SYSTEM": 20,
    "VIN_INTEGRITY": 20,
    "SUSPENSION_STEERING": 15,
    "LAMPS_GLAZING": 10,
}
CHECKPOINT_CODES = tuple(CHECKPOINT_WEIGHTS.keys())
CHECKPOINT_FACTORS = {"PASS": 1.0, "MARGINAL": 0.5, "FAIL": 0.0}
ADEQUACY_PASS_THRESHOLD = 70.00
AUTO_FAIL_CHECKPOINTS = ("STRUCTURAL_FRAME", "VIN_INTEGRITY")

# --- documentation completeness --------------------------------------------
REQUIRED_PART_CLASSES = {
    "SEDAN": ["STRUCTURAL", "RESTRAINT", "LIGHTING"],
    "SUV": ["STRUCTURAL", "RESTRAINT", "LIGHTING"],
    "TRUCK": ["STRUCTURAL", "RESTRAINT", "LIGHTING"],
    "MOTORCYCLE": ["STRUCTURAL", "LIGHTING"],
    "TRAILER": [],
}
REQUIRED_PHOTO_VIEWS = 4
PHOTO_VIEW_CODES = ("FRONT", "REAR", "LEFT", "RIGHT")
COMPLETE_DOCUMENTATION_PCT = 100.00

# --- odometer continuity ---------------------------------------------------
ODOMETER_TOLERANCE_MILES = 0

# --- windows, buffers and limits -------------------------------------------
SUBMISSION_WINDOW_DAYS = 180
APPEAL_WINDOW_DAYS = 30
FLOOD_DECONTAMINATION_BUFFER_MINUTES = 30
PROBATION_REFERRAL_THRESHOLD = 2
DEFAULT_ATTEMPT_LIMIT = 3
MAX_REMANDS_PER_APPEAL = 1

# --- pagination ------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --- money / percentage precision -----------------------------------------
MONEY_SUFFIX = "_cents"
PERCENT_DECIMALS = 2
RATIO_DECIMALS = 4

# --- convenient test defaults ---------------------------------------------
TEST_DEFAULTS = {
    "ACV_CENTS": 1_000_000,
    "REPAIR_ESTIMATE_CENTS": 800_000,
    "DEPOSIT_CENTS": 500_000,
    "BOND_AMOUNT_CENTS": 2_500_000,
    "STRUCTURAL_AMOUNT_CENTS": 200_000,
    "RESTRAINT_AMOUNT_CENTS": 50_000,
    "LIGHTING_AMOUNT_CENTS": 30_000,
    "STATE_CODE": "NV",
    "OWNER_NAME": "Ada Reyes",
    "BUYER_NAME": "Ben Ortiz",
    "INSURER_NAME": "Cascade Mutual",
    "SLOT_START": "2026-08-10T09:00:00Z",
    "SLOT_END": "2026-08-10T11:00:00Z",
}

# The fee escrowed by a bare application whose only surcharge is the structural one.
BASE_PLUS_STRUCTURAL_FEE_CENTS = BASE_APPLICATION_FEE_CENTS + STRUCTURAL_SURCHARGE_CENTS
