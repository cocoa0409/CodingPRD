"""
Domain constants for the County Land Bank Authority API.

Every value here is stated verbatim in the PRD. The names match the PRD's own
constant names so that a failing assertion points straight at the paragraph
that defines it.
"""

# --- API surface -------------------------------------------------------------
API_PREFIX = "/land-bank"
CLOCK_PATH = "/_clock/set_current_utc"

# The server starts at this fixed logical UTC instant and never reads
# wall-clock time.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- Pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- blight_priority_score ---------------------------------------------------
GRADE_POINTS = {"A": 0, "B": 8, "C": 18, "D": 30, "F": 44}
W_VACANCY = 0.25
VACANCY_CAP_MONTHS = 60
W_COMPLAINT = 1.5
COMPLAINT_TERM_CAP = 12
W_VIOLATION = 3
VIOLATION_TERM_CAP = 15
ADJACENT_INVENTORY_MIN = 2
ADJACENT_INVENTORY_BONUS = 10
W_HOLDING = 0.5
HOLDING_TERM_CAP = 12
SCORE_CEILING = 100

# --- maintenance_order_estimate ---------------------------------------------
MOW_RATE_PER_KSQFT_CENTS = 1850
SECURE_BASE_CENTS = 45000
SECURE_RATE_PER_OPENING_CENTS = 12750
DEMO_BASE_CENTS = 950000
DEMO_RATE_PER_SQFT_CENTS = 62
ASBESTOS_SURCHARGE_PCT = 0.18
ASBESTOS_GRADES = ("D", "F")
COUNTY_OVERHEAD_PCT = 0.065

# --- demolition_run_allocation ----------------------------------------------
MIN_SCORE_THRESHOLD = 40
ADMIN_RATE = 0.075
MAX_PROPERTIES_PER_RUN = 5
DEMOLITION_WINDOW_DAYS = 45

# --- disposition_price_quote -------------------------------------------------
SIDE_LOT_BASE_CENTS = 10000
SIDE_LOT_FREE_AREA_SQFT = 5000
SIDE_LOT_MARGINAL_CENTS_PER_SQFT = 2
SIDE_LOT_ASSESSED_CAP_PCT = 0.25
HOMEOWNER_ASSESSED_PCT = 0.55
HOMEOWNER_FLOOR_CENTS = 100000
DEVELOPER_ASSESSED_PCT = 0.90
DEVELOPER_FLOOR_CENTS = 500000
COMMUNITY_USE_CENTS = 100
STRUCTURE_DISCOUNT_PCT = 0.15
DISCOUNT_GRADES = ("D", "F")

# --- tax_discharge_and_abatement --------------------------------------------
NEGOTIATED_DISCHARGE_CAP_PCT = 0.40
CURE_PERIOD_DAYS = 90
COUNTY_MILLAGE_RATE = 0.0142
ABATEMENT_ANNUAL_CAP_CENTS = 250000
MAX_ABATEMENT_YEARS = 10

# --- buyer_eligibility_evaluation -------------------------------------------
CODE_VIOLATION_BAR = 2
REVERTER_LOOKBACK_DAYS = 1825
SIDE_LOT_MIN_SHARED_BOUNDARY_FEET = 20
DISQUALIFIER_PENALTY = 25

# Disqualifier codes, in the exact order the screening appends them.
DISQUALIFIER_ORDER = (
    "DELINQUENT_TAXES",
    "CODE_VIOLATIONS",
    "RECENT_REVERTER",
    "NONPROFIT_REGISTRATION_MISSING",
    "NOT_ADJACENT_OWNER",
    "INSUFFICIENT_OFFER",
)

# --- funding_ledger_position -------------------------------------------------
RESERVE_FLOOR_PCT = 0.05

# --- hearing_support_ratio ---------------------------------------------------
HEARING_VALIDITY_DAYS = 180
HEARING_QUORUM_COMMENTS = 5
HEARING_SUPPORT_MIN_RATIO = 0.60

# --- other declared limits ---------------------------------------------------
MAX_REVISION_ROUNDS = 2
HOMEOWNER_MAX_CONVEYED = 2
DEMOLITION_BUFFER_HOURS = 72

# Program -> required applicant_type pairing.
PROGRAM_REQUIRED_APPLICANT_TYPE = {
    "SIDE_LOT": "INDIVIDUAL",
    "HOMEOWNER_SALE": "INDIVIDUAL",
    "DEVELOPER_RFP": "DEVELOPER",
    "COMMUNITY_USE": "NONPROFIT",
}

# Custody statuses that count as land bank inventory for the conserved
# inventory-area position.
INVENTORY_CUSTODY_STATUSES = ("ACQUIRED", "LISTED", "REVERTED")
