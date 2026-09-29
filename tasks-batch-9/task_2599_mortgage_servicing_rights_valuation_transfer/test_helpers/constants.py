"""
Literal vocabulary shared by the transfer-desk test suite.

Everything here is either (a) a constant the documented rules name outright,
(b) an enumeration value a documented field admits, or (c) a reusable request
payload for one of the standard pools. Keeping the pools in one place lets an
arithmetic expectation sit next to the inputs that produce it.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
CLOCK_AUG_15 = "2026-08-15T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
CLOCK_TRANSFER_DAY = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Opaque actor identifiers
# ---------------------------------------------------------------------------
ADMIN_ID = "admin-001"
ANALYST_ID = "va-001"
MANAGER_ID = "tm-001"
AGENCY_ID = "ag-001"
AGENCY_ID_2 = "ag-002"
COMPLIANCE_ID = "co-001"
COMPLIANCE_ID_2 = "co-002"
HEDGE_ID = "hd-001"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
ROLE_TYPES = ["SELLER", "BUYER"]
SERVICER_RATINGS = ["TIER_1", "TIER_2", "TIER_3"]
AGENCY_TYPES = ["FNMA", "FHLMC", "GNMA"]
COUNTERPARTY_STATUSES = ["ACTIVE", "SUSPENDED"]

PORTFOLIO_STATUSES = ["DRAFT", "TAPE_LOCKED", "UNDER_CONTRACT", "TRANSFERRED"]
VALUATION_FRESHNESS = ["NONE", "CURRENT", "STALE"]
DELINQUENCY_BUCKETS = [
    "CURRENT", "DQ_30_59", "DQ_60_89", "DQ_90_PLUS", "FORECLOSURE",
]
LOSS_MIT_STATUSES = ["NONE", "TRIAL_MOD", "PERMANENT_MOD", "FORBEARANCE"]
LOAN_STATUSES = ["ACTIVE", "TRANSFERRED"]

VALUATION_METHODS = ["DETERMINISTIC_STATIC", "OAS_SHOCK_WEIGHTED"]
VALUATION_RUN_STATUSES = ["COMPLETED", "STALE", "SUPERSEDED"]
RATE_CURVE_STATUSES = ["ACTIVE", "SUPERSEDED"]

STRATIFICATION_SCHEMES = ["BY_STATE", "BY_NOTE_RATE", "BY_DELINQUENCY"]
NOTE_RATE_BANDS = ["LT_600", "600_699", "700_PLUS"]
BID_PACKAGE_STATUSES = [
    "DRAFT", "STRATIFIED", "PUBLISHED", "BIDDING_SUSPENDED", "AWARDED",
    "CANCELLED",
]
SUSPENDED_REASONS = ["VALUATION_STALE"]
EXCLUSION_REASONS = ["DOCUMENT_DEFECT", "LITIGATION", "INVESTOR_RESTRICTION"]
BID_STATUSES = [
    "SUBMITTED", "COUNTERED", "REVISED", "ACCEPTED", "REJECTED", "LAPSED",
]

AGREEMENT_STATUSES = [
    "DRAFTED", "PENDING_APPROVALS", "APPROVED", "CONDITIONALLY_APPROVED",
    "SETTLED", "HOLDBACK_RELEASED", "CLOSED", "TERMINATED",
]
TERMINATION_REASONS = ["APPROVAL_DENIED"]
APPROVER_TYPES = ["AGENCY", "INVESTOR"]
APPROVAL_DECISIONS = ["APPROVED", "CONDITIONALLY_APPROVED", "DENIED"]
APPROVAL_REQUEST_STATUSES = [
    "PENDING", "APPROVED", "CONDITIONALLY_APPROVED", "DENIED",
]

MAPPING_SCHEMES = ["MSP_TO_MSP", "MSP_TO_LSAMS", "CUSTOM"]
NOTICE_DIMENSION = ["NOT_STARTED", "NOTICES_IN_PROGRESS", "NOTICES_ATTESTED"]
DATA_DIMENSION = ["NOT_STARTED", "MAPPED", "ESCROW_MAPPED", "RECONCILED"]
PIPELINE_DIMENSION = ["NOT_STARTED", "PIPELINE_TRANSFERRED"]
READINESS_STATES = ["NOT_READY", "READY"]
TRANSFER_STATUSES = ["IN_PROGRESS", "COMPLETED"]

NOTICE_TYPES = ["TRANSFEROR_15DAY", "TRANSFEREE_15DAY", "COMBINED"]
NOTICE_COMPLIANCE_STATUSES = ["COMPLIANT", "LATE"]
NOTICE_SENDER_ROLES = ["SellerServicer", "BuyerServicer"]

ERROR_CASE_CATEGORIES = [
    "ESCROW", "SUSPENSE", "LOSS_MIT", "PAYMENT_MISAPPLIED", "OTHER",
]
ERROR_CASE_STATUSES = [
    "OPEN", "ACKNOWLEDGED", "RESOLVED", "REOPENED", "ESCALATED",
]

HEDGE_INSTRUMENTS = ["TBA_LONG", "SWAPTION_RECEIVER", "TREASURY_FUTURE_LONG"]
HEDGE_STATUSES = ["OPEN", "CLOSED"]

RISK_SCORE_VARIANTS = ["PRE_AWARD", "POST_TRANSFER"]
RISK_TIERS = ["LOW", "MEDIUM", "ELEVATED", "HIGH"]
OAS_SCENARIO_LABELS = ["DOWN_50", "BASE", "UP_50"]

# ---------------------------------------------------------------------------
# Named model constants
# ---------------------------------------------------------------------------
REFERENCE_RATE_BPS = 4000
DQ_COST_MULTIPLIER = {
    "CURRENT": 1.0,
    "DQ_30_59": 1.5,
    "DQ_60_89": 2.5,
    "DQ_90_PLUS": 4.0,
    "FORECLOSURE": 6.0,
}
LOSS_MIT_SURCHARGE_CENTS = {
    "NONE": 0,
    "TRIAL_MOD": 2000,
    "PERMANENT_MOD": 1000,
    "FORBEARANCE": 1500,
}
OAS_SCENARIOS = [
    {"label": "DOWN_50", "cpr_multiplier": 1.50, "rate_shift_pct": -0.50,
     "weight": 0.25},
    {"label": "BASE", "cpr_multiplier": 1.00, "rate_shift_pct": 0.00,
     "weight": 0.50},
    {"label": "UP_50", "cpr_multiplier": 0.60, "rate_shift_pct": 0.50,
     "weight": 0.25},
]

CONDITIONAL_HOLDBACK_FLOOR_PCT = 15

TIER_1_MAX_RATIO_PCT = 25.00
TIER_2_MAX_RATIO_PCT = 50.00
TIER_1_RELEASE_PCT = 100
TIER_2_RELEASE_PCT = 50
TIER_3_RELEASE_PCT = 0
REMEDIATION_CHARGE_CAP_FRACTION = 0.40

RATING_PENALTY = {"TIER_1": 0, "TIER_2": 10, "TIER_3": 25}
CAPITAL_TIER_1_CENTS = 1000000000
CAPITAL_TIER_2_CENTS = 500000000
MIN_AGENCY_APPROVALS = 2
APPROVAL_PENALTY_PER_MISSING = 8
COMPLAINT_PENALTY_PER_RATIO_POINT = 3
COMPLAINT_PENALTY_CAP = 30
ACK_BREACH_PENALTY = 5
RESOLUTION_BREACH_PENALTY = 10
SLA_PENALTY_CAP = 20
MIN_BIDDER_SCORE = 40
TIER_LOW_MIN_SCORE = 80
TIER_MEDIUM_MIN_SCORE = 60
TIER_ELEVATED_MIN_SCORE = 40

STATUTORY_LEAD_DAYS = 15
OAD_FACTOR = {
    "TBA_LONG": 4.5,
    "SWAPTION_RECEIVER": 6.0,
    "TREASURY_FUTURE_LONG": 5.5,
}

ACK_WINDOW_DAYS = 5
RESOLUTION_WINDOW_DAYS = 30
REOPEN_WINDOW_DAYS = 60
MAX_REOPENS = 2
ONBOARDING_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Counterparties
# ---------------------------------------------------------------------------
SELLER_ALPHA = {
    "legal_name": "Alpha Servicing LLC",
    "role_type": "SELLER",
    "net_worth_cents": 500000000,
    "servicer_rating": "TIER_1",
    "agency_approvals": ["FNMA", "FHLMC"],
}
BUYER_BRAVO = {
    "legal_name": "Bravo Servicing Inc",
    "role_type": "BUYER",
    "net_worth_cents": 1200000000,
    "servicer_rating": "TIER_1",
    "agency_approvals": ["FNMA"],
}
BUYER_CHARLIE = {
    "legal_name": "Charlie Servicing LLC",
    "role_type": "BUYER",
    "net_worth_cents": 1200000000,
    "servicer_rating": "TIER_1",
    "agency_approvals": ["FNMA"],
}

# ---------------------------------------------------------------------------
# Assumption vector and rate curves
# ---------------------------------------------------------------------------
ASSUMPTION_DESK_BASE = {
    "assumption_name": "desk-base",
    "cpr_pct": 8.0,
    "discount_rate_pct": 10.0,
    "cost_to_service_annual_cents": 9000,
    "float_earnings_rate_pct": 4.0,
    "projection_years": 3,
}
CURVE_C1 = {
    "as_of_date": "2026-07-31",
    "base_rate_bps": 4000,
    "primary_secondary_spread_bps": 85,
}
CURVE_C2 = {
    "as_of_date": "2026-08-20",
    "base_rate_bps": 4050,
    "primary_secondary_spread_bps": 85,
}

# ---------------------------------------------------------------------------
# Loan pools
#
# Pool T  four identical 10000050-cent loans in four different states.
# Pool V  three heterogeneous loans; V2 is delinquent and in forbearance.
# Pool M  a single loan, used where one loan makes the arithmetic legible.
# ---------------------------------------------------------------------------
def _loan(number, upb, rate, escrow, suspense, bucket, loss_mit, state):
    return {
        "loan_number": number,
        "upb_cents": upb,
        "note_rate_pct": rate,
        "servicing_fee_bps": 25,
        "escrow_balance_cents": escrow,
        "suspense_balance_cents": suspense,
        "delinquency_bucket": bucket,
        "loss_mit_status": loss_mit,
        "state_code": state,
    }


LOANS_T = [
    _loan("T-0001", 10000050, 6.5, 100000, 25000, "CURRENT", "NONE", "CA"),
    _loan("T-0002", 10000050, 6.5, 100000, 25000, "CURRENT", "NONE", "TX"),
    _loan("T-0003", 10000050, 6.5, 100000, 25000, "CURRENT", "NONE", "FL"),
    _loan("T-0004", 10000050, 6.5, 100000, 25000, "CURRENT", "NONE", "NY"),
]
LOANS_V = [
    _loan("V-0001", 20000000, 6.5, 300000, 0, "CURRENT", "NONE", "CA"),
    _loan("V-0002", 15000000, 7.25, 200000, 50000, "DQ_60_89", "FORBEARANCE",
          "TX"),
    _loan("V-0003", 10000000, 5.75, 150000, 0, "CURRENT", "NONE", "FL"),
]
LOANS_M = [
    _loan("M-0001", 10000050, 6.5, 100000, 25000, "CURRENT", "NONE", "CA"),
]

# Pool T aggregates and valuations at curve C1 under the desk-base assumptions.
POOL_T_TOTAL_UPB_CENTS = 40000200
POOL_T_CUSTODIAL_FUNDS_CENTS = 500000
POOL_T_STATIC_VALUE_CENTS = 171576
POOL_T_OAS_VALUE_CENTS = 170962

# Pool V aggregates and valuations at curve C1 under the desk-base assumptions.
POOL_V_TOTAL_UPB_CENTS = 45000000
POOL_V_STATIC_VALUE_CENTS = 209186
POOL_V_STATIC_VALUE_BPS = 46.49
POOL_V_OAS_VALUE_CENTS = 208484
POOL_V_OAS_VALUE_BPS = 46.33
POOL_V_OAS_SCENARIO_VALUES = {
    "DOWN_50": 188266,
    "BASE": 209186,
    "UP_50": 227299,
}

# Pool M aggregates and valuation at curve C1 under the desk-base assumptions.
POOL_M_TOTAL_UPB_CENTS = 10000050
POOL_M_STATIC_VALUE_CENTS = 42894

# ---------------------------------------------------------------------------
# Standard marketing window and trade terms
# ---------------------------------------------------------------------------
MARKETING_START_AT = "2026-08-01T00:00:00Z"
BID_DEADLINE_AT = "2026-08-15T00:00:00Z"
SALE_DATE = "2026-08-05"
TRANSFER_DATE = "2026-09-01"
RESERVE_PRICE_FLOOR_PCT = 95

STANDARD_BID = {"price_bps": 118, "holdback_pct": 6}
STANDARD_AWARD_TERMS = {"rep_warrant_days": 30, "indemnification_days": 45}
