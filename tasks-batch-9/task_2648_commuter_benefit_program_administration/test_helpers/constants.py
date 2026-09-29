"""Business constants for the Commuter Benefit Program Administration API.

Every value here is declared by the PRD narrative (rounding discipline, the
logical clock, the ordinance thresholds, the invoice pricing constants and the
payroll charge rollup constants).  Tests import these rather than repeating
magic numbers so that a single pinned constant is asserted in exactly one place.
"""

# --- Logical clock (PRD 2.5) ---------------------------------------------------
# "At process startup the logical clock reads exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
CLOCK_PATH = "/_clock/set_current_utc"

# --- Regions ------------------------------------------------------------------
REGION_SFO = "US-CA-SFO"
REGION_NYC = "US-NY-NYC"
REGION_CHI = "US-IL-CHI"
REGION_SEA = "US-WA-SEA"
REGION_AUS = "US-TX-AUS"

ALL_REGION_CODES = [REGION_SFO, REGION_NYC, REGION_CHI, REGION_SEA, REGION_AUS]

# Regions covered by a local commuter benefit ordinance.
COVERED_REGION_CODES = [REGION_SFO, REGION_NYC, REGION_SEA]

# Regional procurement surcharge percentages applied to each invoice line.
REGION_SURCHARGE_PCT = {
    REGION_SFO: 7.5,
    REGION_NYC: 6.25,
    REGION_CHI: 5.0,
    REGION_SEA: 4.0,
    REGION_AUS: 2.5,
}

# --- Order batch invoice pricing ----------------------------------------------
BULK_DISCOUNT_TIER_1_MAX_LINES = 4
BULK_DISCOUNT_TIER_2_MAX_LINES = 9
BULK_DISCOUNT_TIER_1_PCT = 0.0
BULK_DISCOUNT_TIER_2_PCT = 1.5
BULK_DISCOUNT_TIER_3_PCT = 3.0

# --- Payroll charge rollup ----------------------------------------------------
ADMIN_FEE_PER_PARTICIPANT_CENTS = 425
ADMIN_FEE_MINIMUM_CENTS = 5000
FEE_WAIVER_TIER_2_MIN_CENTS = 50000
FEE_WAIVER_TIER_3_MIN_CENTS = 200000

# --- Ordinance compliance -----------------------------------------------------
ORDINANCE_EMPLOYEE_THRESHOLD = 20
ORDINANCE_MINIMUM_TRANSIT_LIMIT_CENTS = 30000

# --- Card spending ------------------------------------------------------------
TRANSIT_MCC_SET = [4111, 4112, 4131, 4789]
PARKING_MCC_SET = [7523]
AUTO_SUBSTANTIATION_CEILING_CENTS = 2500

# --- Loop bounds --------------------------------------------------------------
MEDIA_REISSUE_LIMIT = 2
REISSUE_FEE_ESCALATION_MULTIPLIER = 2
MAX_SUBSTANTIATION_REOPENS = 2
MID_MONTH_CHANGE_LIMIT = 1

SECONDS_PER_DAY = 86400

# --- Enumerations -------------------------------------------------------------
CATEGORY_TYPES = ["TRANSIT_PASS", "VANPOOL", "PARKING"]
LIMIT_GROUPS = ["TRANSIT", "PARKING"]
PAYROLL_CYCLES = ["SEMI_MONTHLY", "MONTHLY"]
SPILL_POLICIES = ["SPILL_TO_POSTTAX", "REJECT_OVERAGE"]
ROLLOVER_POLICIES = ["NO_ROLLOVER", "CAP_ROLLOVER", "FULL_ROLLOVER"]
MEDIA_TYPES = ["PAPER_PASS", "SMART_CARD_LOAD", "DEBIT_CARD"]
DOC_TYPES = ["RECEIPT", "FARE_STATEMENT", "PARKING_INVOICE", "EMPLOYER_ATTESTATION"]
UNDELIVERED_REASONS = ["NEVER_ARRIVED", "LOST", "STOLEN", "DAMAGED"]

LEDGER_ENTRY_TYPES = [
    "ROLLOVER_IN",
    "CONTRIBUTION",
    "CONTRIBUTION_ADJUSTMENT",
    "SPEND",
    "SPEND_REVERSAL",
    "FUNDING_REVERSAL",
    "REPLACEMENT_FEE",
    "FORFEITURE",
    "REFUND",
]

# --- Employer defaults declared by the PRD ------------------------------------
DEFAULT_PRETAX_RATIO_CAP_PCT = 100
DEFAULT_SPILL_POLICY = "SPILL_TO_POSTTAX"
DEFAULT_ROLLOVER_POLICY = "CAP_ROLLOVER"
DEFAULT_ROLLOVER_CAP_CENTS = 5000
DEFAULT_FORFEITURE_GRACE_DAYS = 30
DEFAULT_FULFILLMENT_LEAD_DAYS = 5
DEFAULT_MEDIA_LEAD_DAYS = 3
DEFAULT_REPLACEMENT_FEE_CENTS = 500

# --- Pagination (PRD 2.3) -----------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
