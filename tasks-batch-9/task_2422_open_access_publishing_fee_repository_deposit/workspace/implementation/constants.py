"""Enumerations and pinned constants drawn from the PRD and scaffold."""

# ---- enums --------------------------------------------------------------
SCREENING_STATUSES = ("UNSCREENED", "CLEARED", "WATCHLIST", "PREDATORY_FLAGGED", "BLOCKED")
OA_MODELS = ("FULLY_OA", "HYBRID", "SUBSCRIPTION")
AGREEMENT_COVERED_OA_MODELS = ("FULLY_OA", "HYBRID")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "EXHAUSTED", "EXPIRED")
COVERAGE_TYPES = ("FULL_APC", "CAPPED_APC", "READ_ONLY")
AFFILIATION_STATUSES = (
    "ELIGIBLE_FACULTY",
    "ELIGIBLE_POSTDOC",
    "ELIGIBLE_GRAD",
    "VISITING",
    "EMERITUS",
    "UNAFFILIATED",
)
MANDATE_TYPES = ("NONE", "GREEN_OA", "GOLD_OA", "IMMEDIATE_CC_BY")
LICENSE_REQUIREMENTS = ("ANY", "CC_BY", "CC_BY_OR_NC")
GRANT_STATUSES = ("ACTIVE", "CLOSED")
GRANT_MANDATE_STATUSES = ("IN_PROGRESS", "SATISFIED", "BREACHED")
FUNDING_STATUSES = (
    "DRAFT",
    "ELIGIBILITY_CHECKED",
    "FUNDING_REQUESTED",
    "FUNDED",
    "PARTIALLY_FUNDED",
    "SELF_FUNDED",
    "DECLINED",
)
COMPLIANCE_STATUSES = ("PENDING_DEPOSIT", "EMBARGOED", "COMPLIANT", "NON_COMPLIANT", "EXEMPT")
ELIGIBILITY_ROUTES = ("TA_FULL", "TA_CAPPED", "FUND_APC", "AUTHOR_PAYS")
DETERMINATION_BASES = ("PROVISIONAL", "FINAL")
DETERMINATION_REASONS = (
    "TA_FULL_COVERAGE",
    "TA_CAPPED_COVERAGE",
    "NO_COVERAGE_FUND_ELIGIBLE",
    "NO_COVERAGE_AUTHOR_PAYS",
    "PREDATORY_FLAGGED_NO_INSTITUTIONAL_FUNDS",
)
FUND_STATUSES = ("OPEN", "FROZEN")
FUND_REQUEST_STATUSES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "INFO_REQUESTED",
    "APPROVED",
    "REJECTED",
    "WITHDRAWN",
    "PAID",
)
ALLOCATION_STATUSES = ("ENCUMBERED", "DISBURSED", "RELEASED")
INVOICE_STATUSES = ("RECEIVED", "VALIDATED", "DISPUTED", "APPROVED_FOR_PAYMENT", "PAID")
VALIDATION_OUTCOMES = ("MATCH", "WITHIN_TOLERANCE", "DISCOUNT_SHORTFALL", "AMOUNT_VARIANCE")
DEPOSIT_VERSION_LABELS = ("ACCEPTED_MANUSCRIPT", "VERSION_OF_RECORD")
DEPOSIT_LICENSES = ("CC_BY", "CC_BY_NC", "CC_BY_NC_ND", "ALL_RIGHTS_RESERVED")
DEPOSIT_STATUSES = ("DRAFT", "SUBMITTED", "INGESTED", "SUPERSEDED")
DECISIONS = ("APPROVE", "REJECT")
CURATION_DECISIONS = ("INGEST", "RETURN")
ANALYTICS_BASES = ("ENCUMBRANCE", "CASH")

# ---- patterns -----------------------------------------------------------
PUBLISHER_CODE_PATTERN = r"^[A-Z0-9]{2,16}$"
COUNTRY_CODE_PATTERN = r"^[A-Z]{2}$"
ISSN_PATTERN = r"^\d{4}-\d{3}[\dX]$"
ORCID_PATTERN = r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$"
CHECKSUM_PATTERN = r"^[0-9a-f]{64}$"

# ---- screening weights (scaffold predatory_screening_score) -------------
W_NO_DOAJ = 25
W_NO_COPE = 15
W_NO_BOARD = 20
W_RETRACTION_CAP = 25
RETRACTION_MULTIPLIER = 5
W_FAST_REVIEW = 15
PEER_REVIEW_MIN_DAYS = 14
TRANSPARENCY_CREDIT = "0.1"
BLOCK_MIN = 85
FLAG_MIN = 60
WATCH_MIN = 35

AUTHOR_GUIDANCE = {
    "CLEARED": "Venue cleared: institutional APC funds and agreement coverage may be used.",
    "WATCHLIST": "Venue on watchlist: confirm indexing and peer-review claims before submitting.",
    "PREDATORY_FLAGGED": "Venue flagged as predatory: no institutional funds; deposit the accepted manuscript instead.",
    "BLOCKED": "Venue blocked: eligibility checks are refused; contact the scholarly communications office.",
}

# ---- fiscal / ledger constants -----------------------------------------
FUND_FREEZE_THRESHOLD_PCT = "0.98"
DEFAULT_ANNUAL_CAP_CENTS = 500000
DEFAULT_REQUIRED_EMBARGO_MONTHS = 12

# ---- invoice pricing constants -----------------------------------------
VARIANCE_TOLERANCE_CENTS = 100
DISCOUNT_EPSILON = "0.0001"
TIER1_MIN_CENTS = 500000
TIER2_MIN_CENTS = 2000000
TIER3_MIN_CENTS = 5000000
TIER1_PCT = "0.10"
TIER2_PCT = "0.15"
TIER3_PCT = "0.20"

# ---- identifier minting -------------------------------------------------
DOI_PREFIX = "10.5555/"
HANDLE_PREFIX = "hdl:2027/ir."

# ---- coverage adjacency -------------------------------------------------
COVERAGE_GAP_DAYS = 1
