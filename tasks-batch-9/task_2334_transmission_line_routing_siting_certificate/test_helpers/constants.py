"""Domain thresholds and constants stated in the PRD."""

# --- Logical clock (PRD §2.6) -------------------------------------------------
#: "Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Need case (PRD §3.1) ----------------------------------------------------
#: "a value of at least 1.1500 certifies the study, and anything below it does not"
NEED_MARGIN_THRESHOLD = 1.1500
#: "the requirement that the study have at least two screened-in alternatives"
MIN_SCREENED_IN_ALTERNATIVES = 2

# --- Constraint score (PRD §3.2) ---------------------------------------------
W_LAND_USE = 0.25
W_ENVIRONMENTAL = 0.35
W_CULTURAL = 0.25
W_ENGINEERING = 0.15
#: "Cap that base rating at 4.50 per segment"
BASE_SCORE_CAP = 4.50
#: "the environmental and cultural ratings are replaced by the worst-case value 5"
WORST_CASE_RATING = 5
VOLTAGE_MULTIPLIERS = {"KV_138": 1.00, "KV_345": 1.15, "KV_500": 1.30}
#: "a route may be nominated only when that density is no greater than 4.00"
DENSITY_LIMIT = 4.00
MIN_SEGMENT_RATING = 0
MAX_SEGMENT_RATING = 5

# --- Public involvement (PRD §3.4) -------------------------------------------
MIN_COMMENT_WINDOW_DAYS = 30
MAX_COMMENT_WINDOW_DAYS = 90
#: "a route whose refinement_round has already reached 3"
MAX_REFINEMENT_ROUNDS = 3
#: "at least two recorded open houses spanning at least two distinct counties"
MIN_OPEN_HOUSES = 2
MIN_OPEN_HOUSE_COUNTIES = 2

# --- Filing and docket (PRD §3.5, §3.6) --------------------------------------
#: "at least twenty-five thousand dollars expressed in cents, that is 2,500,000 cents"
MIN_FILING_FEE_CENTS = 2_500_000
#: "decision_deadline_at is computed as the filing instant plus 365 days plus suspension_days"
STATUTORY_FILING_PERIOD_DAYS = 365
#: "slack of fewer than 180 days makes it AT_RISK"
AT_RISK_SLACK_DAYS = 180
#: "an application whose amendment_round has already reached 2"
MAX_AMENDMENT_ROUNDS = 2
#: "suspension_days is set to 90" on the second granted petition
SECOND_INTERVENTION_SUSPENSION_DAYS = 90
#: "pad it by two hours on each side" when checking hearing window conflicts
HEARING_BUFFER_MINUTES = 120

# --- Escrow requirement (PRD §3.7) -------------------------------------------
#: "a base below five million dollars, that is below 500,000,000 cents, is TIER_1"
TIER_2_FLOOR_CENTS = 500_000_000
#: "a base below twenty million dollars, that is below 2,000,000,000 cents, is TIER_2"
TIER_3_FLOOR_CENTS = 2_000_000_000
CONTINGENCY_RATES = {"TIER_1": 0.10, "TIER_2": 0.14, "TIER_3": 0.18}
#: "count the conditions ... whose severity_weight is 4 or greater"
HEAVY_CONDITION_WEIGHT = 4
#: "twenty-five thousand dollars — 2,500,000 cents — per such heavy condition"
CONDITION_SURCHARGE_CENTS = 2_500_000
MIN_SEVERITY_WEIGHT = 1
MAX_SEVERITY_WEIGHT = 5

# --- Easement acquisition (PRD §3.8) -----------------------------------------
#: "1.00 for the first offer, 1.05 for the second, 1.12 for the third"
OFFER_ESCALATIONS = {1: 1.00, 2: 1.05, 3: 1.12}
#: "a tract whose offer_round has already reached 3"
MAX_OFFER_ROUNDS = 3
#: "at least two offers must already have been extended — that is, offer_round must be at least 2"
MIN_OFFER_ROUNDS_FOR_CONDEMNATION = 2
#: "deposit_cents multiplied by the statutory rate of 0.06"
STATUTORY_INTEREST_RATE = 0.06
#: "the logical clock is strictly earlier than 30 days after paid_at"
RESCISSION_WINDOW_DAYS = 30

# --- Compliance (PRD §3.9) ---------------------------------------------------
#: "4 for MINOR, 12 for MAJOR, 30 for SEVERE"
SEVERITY_POINTS = {"MINOR": 4, "MAJOR": 12, "SEVERE": 30}
#: "subtract 1 from that weight, multiply the remainder by 0.2, add 1"
WEIGHT_STEP = 0.2
#: "a CORRECTED finding contributes half of it"
CORRECTION_CREDIT_FACTOR = 0.5
STARTING_COMPLIANCE_INDEX = 100
#: "if compliance_index_rolling is strictly below 60.00 the posture is STOP_WORK"
STOP_WORK_FLOOR = 60.00
#: "if compliance_index_cumulative is strictly below 25.00 the posture is REVOKED"
REVOCATION_FLOOR = 25.00
#: "compliance_index_cumulative must be at least 75.00"
CLOSEOUT_FLOOR = 75.00

# --- Pagination (PRD §2.3) ---------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

#: Tolerance for the two-decimal scores, densities, indices and deductions.
SCORE_TOLERANCE = 0.005
#: Tolerance for the four-decimal study ratios.
RATIO_TOLERANCE = 0.00005
