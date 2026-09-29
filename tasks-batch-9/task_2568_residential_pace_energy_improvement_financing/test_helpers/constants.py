"""Program constants, pinned reference values and enum vocabularies.

Every value here is stated in the PRD.  Nothing is invented: the calculation
constants come from the arithmetic sections, the enum tuples from the field
vocabularies, and the pinned reference figures from the worked examples the
PRD spells out inline.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# "The startup default is exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_PROPERTY_OWNER = "PropertyOwner"
ROLE_CONTRACTOR = "Contractor"
ROLE_UNDERWRITING_ANALYST = "UnderwritingAnalyst"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_FUNDING_OFFICER = "FundingOfficer"
ROLE_COUNTY_OFFICER = "CountyOfficer"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    ROLE_PROPERTY_OWNER,
    ROLE_CONTRACTOR,
    ROLE_UNDERWRITING_ANALYST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FUNDING_OFFICER,
    ROLE_COUNTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
)

# Roles whose X-User-ID is an entity identifier rather than an opaque operator
# id: the PropertyOwner's is the parcel id, the Contractor's is the contractor id.
ENTITY_BACKED_ROLES = (ROLE_PROPERTY_OWNER, ROLE_CONTRACTOR)

# ---------------------------------------------------------------------------
# Counties
# ---------------------------------------------------------------------------

COUNTY_SAN_DIEGO = "06073"
COUNTY_LOS_ANGELES = "06037"
COUNTY_MIAMI_DADE = "12086"

COUNTY_CODES = (COUNTY_SAN_DIEGO, COUNTY_LOS_ANGELES, COUNTY_MIAMI_DADE)
DEEMED_CONSENT_COUNTIES = (COUNTY_SAN_DIEGO, COUNTY_LOS_ANGELES)
WRITTEN_CONSENT_ONLY_COUNTIES = (COUNTY_MIAMI_DADE,)

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------

PREFERRED_LANGUAGES = ("EN", "ES")
OCCUPANCY_TYPES = ("OWNER_OCCUPIED", "RENTAL", "VACANT")

LIEN_STATUSES = ("ACTIVE", "RELEASED")
CONSENT_RESPONSES = (
    "NOT_NOTIFIED",
    "PENDING",
    "CONSENTED",
    "DECLINED",
    "DEEMED_CONSENTED",
)

PRODUCT_CATEGORIES = ("SOLAR_PV", "HVAC", "ROOF", "WINDOWS", "WATER_EFFICIENCY")
PRODUCT_STATUSES = ("ACTIVE", "RETIRED")

CONTRACTOR_ENROLLMENT_STATUSES = (
    "PENDING_REVIEW",
    "ENROLLED",
    "PROBATION",
    "SUSPENDED",
    "TERMINATED",
)

APPLICATION_STATUSES = (
    "DRAFT",
    "UNDER_REVIEW",
    "NEEDS_CURE",
    "CONSENT_PENDING",
    "APPROVED",
    "FUNDING_PENDING",
    "FUNDING_HELD",
    "FUNDED",
    "ASSESSED",
    "DECLINED",
    "WITHDRAWN",
)
VALUATION_BASES = ("ASSESSED", "MARKET")
DECLINE_REASON_CODES = (
    "CLTV_LIMIT",
    "PTV_LIMIT",
    "EQUITY_FLOOR",
    "SIR_FLOOR",
    "BANKRUPTCY",
    "LENDER_DECLINED",
    "CURE_ROUNDS_EXHAUSTED",
)
CONSENT_POSTURES = ("NOT_STARTED", "PENDING", "CLEARED", "VETOED")
FUNDING_HOLD_REASONS = ("CONTRACTOR_PROBATION", "CONTRACTOR_SUSPENSION")
CURE_REASON_CODES = (
    "TAX_DELINQUENCY",
    "MEASURE_SIR_FAIL",
    "APPRAISAL_MISSING",
    "LENDER_UNRESPONSIVE",
)

MEASURE_STATUSES = ("PROPOSED", "APPROVED", "INELIGIBLE", "COMPLETED")

AGREEMENT_STATUSES = ("ISSUED", "SIGNED", "EFFECTIVE", "RECORDED", "RESCINDED", "VOID")
CERTIFICATE_STATUSES = (
    "CONTRACTOR_ATTESTED",
    "HOMEOWNER_SIGNED",
    "VERIFIED",
    "REJECTED",
)
DISBURSEMENT_STATUSES = ("REQUESTED", "HELD", "RELEASED", "REVERSED")

COMPLAINT_CATEGORIES = (
    "WORKMANSHIP_DEFECT",
    "INCOMPLETE_WORK",
    "SAVINGS_SHORTFALL",
    "PERMIT_FAILURE",
)
COMPLAINT_SEVERITIES = ("MINOR", "MAJOR", "SEVERE")
COMPLAINT_STATUSES = (
    "OPEN",
    "REMEDY_ORDERED",
    "CLOSED_REMEDIED",
    "CLOSED_DENIED",
    "ESCALATED_RECOURSE",
)

BILLING_STATUSES = ("PENDING_ROLL", "ON_ROLL", "PAID_OFF")
ASSESSMENT_LIEN_STATUSES = ("SENIOR_RECORDED", "LIEN_SALE_REFERRED", "RELEASED")
TRANSFER_STATUS_ON_ASSESSMENT = ("NONE", "QUOTED", "ASSUMED", "PAID_OFF_AT_SALE")
INSTALLMENT_STATUSES = ("SCHEDULED", "BILLED", "PAID", "DELINQUENT", "CANCELLED")
TRANSFER_MODES = ("ASSUME_WITH_PROPERTY", "PAYOFF_AT_CLOSING")
TRANSFER_STATUSES = (
    "QUOTED",
    "RECORDED_ASSUMED",
    "RECORDED_PAID_OFF",
    "VOID_STALE",
    "EXPIRED",
)

# ---------------------------------------------------------------------------
# Arithmetic constants
# ---------------------------------------------------------------------------

DISCOUNT_RATE_BPS = 300
AF_DECIMALS = 10

# The only useful lives products may declare, and the pinned annuity factor for
# each one at the 3% program discount rate.
ANNUITY_FACTOR_3PCT = {
    10: "8.5302028368",
    15: "11.9379350868",
    18: "13.7535130795",
    20: "14.8774748605",
    25: "17.4131476913",
}

SIR_FLOOR_BPS = 10000

CLTV_CAP_BPS = 9700
PTV_CAP_BPS = 1500
EQUITY_FLOOR_BPS = 1000
APPRAISAL_STALENESS_DAYS = 180

ADMIN_FEE_BPS = 250
COUNTY_RECORDING_FEE_CENTS = 9500

ANNUAL_SERVICING_FEE_CENTS = 4000
DUE_MONTH = 12
DUE_DAY = 10

# Pinned amortization annuity factors at 800 bps.
ANNUITY_FACTOR_800BPS = {20: "9.8181474074", 25: "10.6747761886"}

ALLOWED_TERM_YEARS = (10, 15, 18, 20, 25)

BASE_PENALTY_BPS = 1000
MONTHLY_PENALTY_BPS = 150
PENALTY_CAP_BPS = 2400
REFERRED_PENALTY_CAP_BPS = 3000
LIEN_REFERRAL_FEE_CENTS = 15000
DAYS_PER_PENALTY_MONTH = 30

PAYOFF_ADMIN_FEE_CENTS = 7500
PREMIUM_TIER1_CEILING_CENTS = 1000000
PREMIUM_TIER2_CEILING_CENTS = 5000000
PREMIUM_TIER1_BPS = 0
PREMIUM_TIER2_BPS = 200
PREMIUM_TIER3_BPS = 350
DAY_COUNT_BASIS = 365

MINOR_PENALTY_BPS = 300
MAJOR_PENALTY_BPS = 800
SEVERE_PENALTY_BPS = 2000
PROBATION_THRESHOLD_BPS = 9000
SUSPENSION_THRESHOLD_BPS = 7000
REINSTATE_TRAILING_BPS = 9000
REINSTATE_LIFETIME_BPS = 8000
TRAILING_WINDOW_DAYS = 730

CONSENT_WINDOW_DAYS = 30

RESCISSION_BUSINESS_DAYS = 3
PROGRAM_HOLIDAYS = (
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
    "2027-01-01",
    "2027-07-03",
)

QUOTE_VALID_DAYS = 30
QUOTE_BUFFER_DAYS = 5

MIN_MEASURE_COST_CENTS = 100000
MAX_MEASURES_PER_APPLICATION = 5
MAX_COMPLAINTS_PER_APPLICATION = 3
MIN_WARRANTY_YEARS = 5
MAX_CURE_ROUNDS = 2
MAX_TAX_DELINQUENCIES = 1

FIRST_TAX_YEAR_MIN = 2027
FIRST_TAX_YEAR_MAX = 2060

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
