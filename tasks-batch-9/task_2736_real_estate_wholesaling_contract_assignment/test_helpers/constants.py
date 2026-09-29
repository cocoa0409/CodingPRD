"""
Domain constants for the Wholesaling Assignment Desk API.

Every value here is stated verbatim in the PRD narrative (sections 2.3 through
2.12 and 3.1 through 3.9). Nothing is inferred.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

# "On a fresh server that instant is 2026-08-01T00:00:00Z"
DEFAULT_CURRENT_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
MIN_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Comparable qualification and valuation (PRD 3.4)
# ---------------------------------------------------------------------------

DISTANCE_MAX_MILES = 0.50
RECENCY_MAX_DAYS = 180
# "the absolute difference between the comparable's gla_sqft and
#  subject_gla_sqft, multiplied by one hundred, must be at most
#  subject_gla_sqft multiplied by twenty"
GLA_BAND_NUMERATOR = 100
GLA_BAND_MULTIPLIER = 20
MIN_QUALIFYING_COMPS = 3

# Recency weight: "one hundred and eighty-one minus its closed_days_ago"
RECENCY_WEIGHT_BASE = 181

CONSERVATIVE_ARV_MULTIPLIER = 0.70
AGGRESSIVE_ARV_MULTIPLIER = 0.75
CONTINGENCY_MULTIPLIER = 1.10

# "a minimum assignment margin of one million cents"
MIN_ASSIGNMENT_MARGIN_CENTS = 1000000

# ---------------------------------------------------------------------------
# Protection screen (PRD 3.3)
# ---------------------------------------------------------------------------

# "a seller closing-cost allowance of eight percent of the estimated market value"
SELLER_CLOSING_COST_PCT = 0.08
# "A lead is PROTECTED when its equity percentage is at least 0.35"
HIGH_EQUITY_PCT = 0.35
EQUITY_PCT_DECIMAL_PLACES = 4

# ---------------------------------------------------------------------------
# Equity floor on contract creation (PRD 3.5)
# ---------------------------------------------------------------------------

# "the seller must be left with at least sixty percent of their statutory equity"
EQUITY_FLOOR_PCT = 0.60

# ---------------------------------------------------------------------------
# Protection-tier assignment fee cap (PRD 3.7)
# ---------------------------------------------------------------------------

FEE_CAP_PCT_STANDARD = 0.12
FEE_CAP_PCT_ELEVATED = 0.08
FEE_CAP_PCT_PROTECTED = 0.05

FEE_CAP_PCT_BY_TIER = {
    "STANDARD": FEE_CAP_PCT_STANDARD,
    "ELEVATED": FEE_CAP_PCT_ELEVATED,
    "PROTECTED": FEE_CAP_PCT_PROTECTED,
}

# ---------------------------------------------------------------------------
# Settlement component rates (PRD 3.8)
# ---------------------------------------------------------------------------

TITLE_HOLDBACK_RATE = 0.0325
STATE_TRANSFER_SURCHARGE_RATE = 0.0075
MARKETING_RECOVERY_RATE = 0.0155

# ---------------------------------------------------------------------------
# Double-close funding schedule (PRD 3.8)
# ---------------------------------------------------------------------------

CLOSING_COST_GROSS_UP_RATE = 0.021

TIER_1_CEILING_CENTS = 15000000
TIER_2_CEILING_CENTS = 30000000

TIER_1_RATE = 0.0300
TIER_2_RATE = 0.0225
TIER_3_RATE = 0.0175

TIER_1_MIN_FEE_CENTS = 25000
TIER_2_MIN_FEE_CENTS = 45000
TIER_3_MIN_FEE_CENTS = 70000

# ---------------------------------------------------------------------------
# Buyer capital reconciliation (PRD 2.11, 3.6)
# ---------------------------------------------------------------------------

# "PRIORITY when available_funds_cents is at least twenty-five million cents"
PRIORITY_TIER_MIN_AVAILABLE_CENTS = 25000000

# "The live statuses are SUBMITTED, COUNTERED_BY_WHOLESALER,
#  REVISED_BY_BUYER and ACCEPTED"
LIVE_OFFER_STATUSES = (
    "SUBMITTED",
    "COUNTERED_BY_WHOLESALER",
    "REVISED_BY_BUYER",
    "ACCEPTED",
)

RELEASED_OFFER_STATUSES = ("CONSUMED", "WITHDRAWN", "LAPSED")

# ---------------------------------------------------------------------------
# Temporal offsets (PRD 2.5, 2.12)
# ---------------------------------------------------------------------------

ASSIGNMENT_CUTOFF_HOURS = 48
PROTECTED_COOLING_OFF_HOURS = 72
DOUBLE_CLOSE_BUFFER_HOURS = 48
HOURS_PER_INSPECTION_DAY = 24

# ---------------------------------------------------------------------------
# Negotiation and compliance thresholds (PRD 2.9, 3.7)
# ---------------------------------------------------------------------------

MAX_NEGOTIATION_ROUNDS = 4
COMPLIANCE_HOLD_THRESHOLD = 2

# ---------------------------------------------------------------------------
# Field length limits (PRD 3.1 through 3.9)
# ---------------------------------------------------------------------------

MAX_LEGAL_NAME_LEN = 200
MAX_DISCLOSURE_TEMPLATE_VERSION_LEN = 32
MAX_HEADLINE_LEN = 200
MAX_OWNER_NAME_LEN = 200
MAX_PROPERTY_ADDRESS_LEN = 300
MAX_SIGNATURE_REF_LEN = 120
MAX_DOCUMENT_REF_LEN = 120
MAX_CONTACT_EMAIL_LEN = 200
MAX_TITLE_COMPANY_NAME_LEN = 200
MAX_ESCROW_OFFICER_REF_LEN = 120
MAX_ALLEGATION_NOTE_LEN = 1000

MIN_INSPECTION_PERIOD_DAYS = 1
MAX_INSPECTION_PERIOD_DAYS = 30
MIN_FUNDING_WINDOW_CAPACITY = 1

MAX_COMPARABLES = 20
MAX_REPAIR_SCOPE_ITEMS = 40

# ---------------------------------------------------------------------------
# Non-existent identifiers used by not-found probes
# ---------------------------------------------------------------------------

MISSING_UUID_FF = "00000000-0000-0000-0000-0000000000ff"
MISSING_UUID_AA = "00000000-0000-0000-0000-0000000000aa"
