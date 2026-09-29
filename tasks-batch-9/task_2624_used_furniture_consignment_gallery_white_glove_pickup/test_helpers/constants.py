"""Domain thresholds and factors stated numerically by the PRD."""

SECONDS_PER_DAY = 86_400

# The logical clock reads exactly this before any client has set it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Photographic screening / receiving inspection ---------------------------
PHOTO_WEIGHTS = {
    "surface": 0.45,
    "structure": 0.30,
    "completeness": 0.25,
}

GRADE_LADDER = {
    "REJECTED_BELOW": 3.00,
    "A_AT_OR_ABOVE": 8.50,
    "B_AT_OR_ABOVE": 6.50,
    "C_AT_OR_ABOVE": 4.50,
}

GRADE_FACTORS = {"A": 0.85, "B": 0.70, "C": 0.55, "D": 0.40}

CATEGORY_FACTORS = {
    "SOFA": 0.95,
    "DINING": 1.05,
    "CASEGOOD": 1.00,
    "RUG": 1.10,
    "ART": 1.20,
    "OUTDOOR": 0.85,
}

GRADE_RANKS = {"A": 4, "B": 3, "C": 2, "D": 1, "REJECTED": 0}

# A distance of two or more grades lands the piece in a receiving dispute.
RECEIVING_DISPUTE_MIN_DOWNGRADE = 2

# A lot parent always tickets below the sum of its parts.
LOT_BUNDLE_FACTOR = 0.90

# --- Photo-score fixtures that land on a known grade ------------------------
# (surface, structure, completeness) -> rounded photo_score -> grade
SCORES_GRADE_A = {
    "photo_surface_score": 8.0,
    "photo_structure_score": 9.0,
    "photo_completeness_score": 9.0,
}   # 8.55 -> A
SCORES_GRADE_B = {
    "photo_surface_score": 7.0,
    "photo_structure_score": 6.5,
    "photo_completeness_score": 6.0,
}   # 6.60 -> B
SCORES_GRADE_C = {
    "photo_surface_score": 5.0,
    "photo_structure_score": 5.5,
    "photo_completeness_score": 4.5,
}   # 5.03 -> C
SCORES_GRADE_D = {
    "photo_surface_score": 3.5,
    "photo_structure_score": 4.0,
    "photo_completeness_score": 3.0,
}   # 3.53 -> D
SCORES_GRADE_REJECTED = {
    "photo_surface_score": 2.0,
    "photo_structure_score": 2.0,
    "photo_completeness_score": 2.0,
}   # 2.00 -> REJECTED
# exactly on the C boundary: 0.45*4 + 0.30*5 + 0.25*4.5 = 4.425 -> 4.43 -> D
SCORES_JUST_UNDER_C = {
    "photo_surface_score": 4.0,
    "photo_structure_score": 5.0,
    "photo_completeness_score": 4.5,
}

# --- Pickup surcharge -------------------------------------------------------
PICKUP_SURCHARGE = {
    "BASE_CENTS": 12_000,
    "VOLUME_BLOCK_CUFT": 10,
    "VOLUME_BLOCK_CENTS": 2_500,
    "ELEVATOR_FLAT_CENTS": 3_000,
    "PER_FLIGHT_CENTS": 4_500,
    "MAX_CHARGED_FLIGHTS": 6,
    "EXTREME_CLIMB_CENTS": 8_000,
    "BULKY_FEE_CENTS": 5_500,
    "BULKY_MIN_VOLUME_CUFT": 60,
    "CAP_PCT_OF_DECLARED_VALUE": 0.35,
}

CREW_MULTIPLIERS = {"LTE_2": 1.00, "EQ_3": 1.25, "GTE_4": 1.45}

# A truck needs a 45-minute turnaround gap between consecutive jobs.
TRUCK_TURNAROUND_MINUTES = 45

# --- Floor zones ------------------------------------------------------------
UTILIZATION_BANDS = {"FULL_AT_OR_ABOVE": 1.00, "TIGHT_AT_OR_ABOVE": 0.75}
CLEARANCE_PRICE_THRESHOLD_CENTS = 50_000

# --- Markdown / disposition -------------------------------------------------
DISCOUNT_ELECTED_EXTRA_CUT = 0.10
UNSOLD_TRIGGER_EXTENSION_DAYS_PER_ROUND = 30
MAX_ELECTION_ROUND = 2
DONATE_MAX_PRICE_CENTS = 200_000
DISPOSAL_FEES = {"RETURN_CENTS": 4_000, "DONATION_CENTS": 2_500}

# --- Sale split -------------------------------------------------------------
CATEGORY_BASE_SHARE = {
    "SOFA": 0.50,
    "DINING": 0.55,
    "CASEGOOD": 0.55,
    "RUG": 0.60,
    "ART": 0.65,
    "OUTDOOR": 0.45,
}
PRICE_BAND_BONUS = {
    "BELOW_50000": 0.00,
    "AT_50000_BELOW_150000": 0.05,
    "AT_OR_ABOVE_150000": 0.10,
}
TENURE_PENALTY = 0.05
TENURE_PENALTY_MIN_MARKDOWN_SEQUENCE = 3
SPLIT_PCT_FLOOR = 0.40
SPLIT_PCT_CEILING = 0.70
REGISTER_FLOOR_PCT = 0.80

# --- White-glove delivery ---------------------------------------------------
DELIVERY_FEE = {
    "BASE_CENTS": 7_500,
    "ELEVATOR_FLAT_CENTS": 3_000,
    "PER_FLIGHT_CENTS": 4_500,
    "MAX_CHARGED_FLIGHTS": 6,
    "EXTREME_CLIMB_CENTS": 8_000,
    "ASSEMBLY_CENTS": 4_000,
}
ASSEMBLY_CATEGORIES = ("DINING", "CASEGOOD")
CLAIM_WINDOW_DAYS = 5

# --- Damage claim adjudication ---------------------------------------------
GALLERY_DEDUCTIBLE_CENTS = 5_000
UNDETERMINED_CONSIGNOR_SHARE = 0.50
MAX_RESUBMISSION_COUNT = 2

# --- Shrinkage / payouts / escheatment -------------------------------------
SHRINKAGE_CREDIT_PCT = 0.60
PAYOUT_MINIMUM_CENTS = 2_000
WITHHOLDING_TIERS = {
    "BELOW_100000": 0.00,
    "AT_100000_BELOW_500000": 0.02,
    "AT_OR_ABOVE_500000": 0.03,
}
PROCESSING_FEES = {"ACH": 0, "CHECK": 250, "STORE_CREDIT": 0}
SUSPENSION_BALANCE_THRESHOLD_CENTS = -50_000
DORMANT_DAYS = 365
ESCHEAT_DAYS = 545

# --- Pagination -------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# --- The standard schedule every fixture pins itself to --------------------
# steps: (sequence, start_day_offset, markdown_pct, min_price_cents)
STD_SCHEDULE_STEPS = [
    (1, 0, 0.00, 0),
    (2, 30, 0.15, 0),
    (3, 60, 0.30, 0),
    (4, 90, 0.50, 45_000),
]
STD_UNSOLD_TRIGGER_DAY = 120
STD_ELECTION_WINDOW_DAYS = 14
