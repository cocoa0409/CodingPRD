"""
Domain constants for the Qualified Opportunity Fund compliance API.

Every literal here is stated in the PRD: the API prefix, the logical-clock
origin, the numeric thresholds the calculations use, and the enum member sets.
Tests import these rather than repeating magic values.
"""

# --- API surface ----------------------------------------------------------
API_PREFIX = "/qof"

# --- logical clock --------------------------------------------------------
# The clock reads exactly this value on a fresh database, before any client
# has set it.
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"

# --- envelope -------------------------------------------------------------
REQUEST_ID_PREFIX = "req_"
RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"

# --- pagination -----------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- rounding -------------------------------------------------------------
MONEY_DECIMALS = 2
PERCENT_DECIMALS = 4

# --- deferral window ------------------------------------------------------
DEFERRAL_WINDOW_DAYS = 180

# --- semiannual 90-percent asset test ------------------------------------
QUALIFIED_ASSET_MIN_PCT = 90.0000
SHORTFALL_TARGET_RATIO = 0.90

# --- QOZB three-prong test ------------------------------------------------
GROSS_INCOME_MIN_PCT = 50.0000
INTANGIBLES_MIN_PCT = 40.0000
NQFP_MAX_PCT = 5.0000
MGMT_SAFE_HARBOR_CREDIT = 1.25

# --- substantial improvement ---------------------------------------------
SI_WINDOW_MONTHS = 30
SI_REQUIRED_PCT = 100.0000

# --- working capital safe harbor -----------------------------------------
WCSH_WINDOW_MONTHS = 31
WCSH_PACING_TOLERANCE_PCT = 10.0

# --- failed-test penalty --------------------------------------------------
UNDERPAYMENT_ANNUAL_RATE = 0.08

# --- cure credit netting --------------------------------------------------
CURE_CREDIT_TIER_BREAK = 1000.00
CURE_CREDIT_HIGH_RATE = 0.60
CURE_CREDIT_LOW_RATE = 0.40
CURE_CREDIT_FLOOR = 250.00
MAX_CURE_ATTEMPTS = 2

# --- holding tiers --------------------------------------------------------
FIVE_YEAR_DAYS = 1826
SEVEN_YEAR_DAYS = 2557
TEN_YEAR_DAYS = 3653
STEP_UP_FIVE_PCT = 0.10
STEP_UP_SEVEN_PCT = 0.15

# --- zone tract code ------------------------------------------------------
ZONE_TRACT_CODE_LENGTH = 11

# --- roles ----------------------------------------------------------------
ROLE_FUND_MANAGER = "FundManager"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_INVESTOR = "Investor"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_FUND_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INVESTOR,
    ROLE_PLATFORM_ADMIN,
]

# --- Investor enums -------------------------------------------------------
TAXPAYER_TYPES = ["INDIVIDUAL", "PARTNERSHIP", "C_CORPORATION", "TRUST"]
ATTESTATION_STATUSES = ["PENDING", "ATTESTED", "BLOCKED"]
DEFAULT_TAX_YEAR_END_MONTH = 12
DEFAULT_ATTESTATION_STATUS = "PENDING"

# --- Fund enums -----------------------------------------------------------
FUND_ENTITY_TYPES = ["CORPORATION", "PARTNERSHIP"]
VALUATION_METHODS = ["APPLICABLE_FINANCIAL_STATEMENT", "UNADJUSTED_COST_BASIS"]
DEFAULT_VALUATION_METHOD = "UNADJUSTED_COST_BASIS"
CERTIFICATION_STATUSES = ["DRAFT", "SELF_CERTIFIED", "DECERTIFIED"]
COMPLIANCE_POSTURES = [
    "UNTESTED",
    "COMPLIANT",
    "DEFICIENT",
    "CURE_PENDING",
    "FAILED_FINAL",
]

# --- EligibleGain enums ---------------------------------------------------
GAIN_CHARACTERS = [
    "SHORT_TERM_CAPITAL",
    "LONG_TERM_CAPITAL",
    "SECTION_1231_NET",
    "ORDINARY",
]
DEADLINE_BASES = ["SALE_DATE", "PARTNERSHIP_YEAR_END", "SECTION_1231_YEAR_END"]
GAIN_STATUSES = ["ELIGIBLE", "PARTIALLY_INVESTED", "FULLY_INVESTED", "EXPIRED"]

# --- DeferralElection enums ----------------------------------------------
HOLDING_TIERS = ["UNDER_FIVE", "FIVE_YEAR", "SEVEN_YEAR", "TEN_YEAR"]
ELECTION_STATUSES = [
    "DEFERRED",
    "STEPPED_UP",
    "INCLUDED_PARTIAL",
    "INCLUDED_FULL",
    "REVOKED",
]
REVOKED_REASON_CODES = [
    "NONE",
    "INVESTOR_WITHDRAWAL",
    "FUND_REJECTED",
    "ADMIN_CORRECTION",
]

# --- FundAsset enums ------------------------------------------------------
ASSET_CLASSES = [
    "QOZ_BUSINESS_PROPERTY",
    "QOZB_EQUITY",
    "NONQUALIFIED_FINANCIAL_PROPERTY",
    "CASH",
]
QUALIFICATIONS = ["QUALIFIED", "NONQUALIFIED", "IMPROVEMENT_PENDING"]
ASSET_STATUSES = ["HELD", "IMPROVING", "DISPOSED"]

# --- QOZBusiness enums ---------------------------------------------------
BUSINESS_QUALIFICATION_STATUSES = [
    "UNTESTED",
    "QUALIFIED",
    "AT_RISK",
    "DISQUALIFIED",
]

# --- BusinessTest enums --------------------------------------------------
SAFE_HARBORS = [
    "FIFTY_PCT_HOURS",
    "FIFTY_PCT_AMOUNTS_PAID",
    "MANAGEMENT_AND_TANGIBLE",
    "GROSS_INCOME_ACTUAL",
]
PRONG_VERDICTS = ["PENDING", "PASS", "FAIL"]
BUSINESS_TEST_STATUSES = ["DRAFT", "MEASURED", "PASSED", "FAILED"]

# --- AssetTest enums -----------------------------------------------------
ASSET_TEST_RESULTS = ["PENDING", "PASS", "FAIL"]
ASSET_TEST_STATUSES = ["DRAFT", "MEASURED", "CERTIFIED_PASS", "CERTIFIED_FAIL"]

# --- ImprovementProject enums --------------------------------------------
AGGREGATION_METHODS = ["ASSET_BY_ASSET", "AGGREGATED_GROUP"]
PROJECT_STATUSES = ["OPEN", "SATISFIED", "LAPSED"]

# --- WorkingCapitalPlan enums -------------------------------------------
PLAN_STATUSES = ["DRAFT", "ACTIVE", "COMPLETED", "BLOWN"]

# --- CapitalExpenditure enums -------------------------------------------
EXPENDITURE_KINDS = [
    "CAPITALIZED_IMPROVEMENT",
    "OPERATING_WORKING_CAPITAL",
    "LAND_ACQUISITION",
]

# --- PenaltyAssessment enums --------------------------------------------
CURE_BASES = ["NONE", "REASONABLE_CAUSE", "TREATED_AS_FAILURE"]
ASSESSMENT_STATUSES = ["ASSESSED", "CURE_REQUESTED", "CURED", "UPHELD"]
CURE_DECISIONS = ["APPROVE", "DENY"]

# --- InclusionEvent enums ------------------------------------------------
INCLUSION_EVENT_TYPES = [
    "SALE_OF_INTEREST",
    "GIFT_TRANSFER",
    "FUND_DECERTIFICATION",
    "PARTIAL_REDEMPTION",
    "DEC_31_2026_STATUTORY",
]

# --- StepUpElection enums -----------------------------------------------
STEP_UP_STATUSES = ["GRANTED", "DENIED"]
DENIAL_REASONS = [
    "NONE",
    "HOLD_UNDER_TEN_YEARS",
    "FUND_DECERTIFIED",
    "PRIOR_FULL_INCLUSION",
]

# --- fixed UUIDs used for not-found probes ------------------------------
UNKNOWN_UUID_999 = "00000000-0000-4000-8000-000000000999"
UNKNOWN_UUID_099 = "00000000-0000-4000-8000-000000000099"
