"""Named values the contract fixes: roles, states, schedules and thresholds.

Nothing here is invented. Every number below is written down in the PRD, and the
canonical scenario figures at the bottom are chosen so that the arithmetic they
drive lands on the exact boundaries the contract cares about.
"""

# ─── Roles (PRD §2.1) ─────────────────────────────────

ROLE_DEVELOPER = "Developer"
ROLE_INVESTOR = "Investor"
ROLE_HFA_ALLOCATION_OFFICER = "HfaAllocationOfficer"
ROLE_HFA_COMPLIANCE_OFFICER = "HfaComplianceOfficer"
ROLE_BOND_TRUSTEE = "BondTrustee"
ROLE_SYSTEM_OPERATOR = "SystemOperator"

ALL_ROLES = (
    ROLE_DEVELOPER,
    ROLE_INVESTOR,
    ROLE_HFA_ALLOCATION_OFFICER,
    ROLE_HFA_COMPLIANCE_OFFICER,
    ROLE_BOND_TRUSTEE,
    ROLE_SYSTEM_OPERATOR,
)

# The two roles whose X-User-ID is the id of a stored row (PRD §2.1).
ENTITY_BACKED_ROLES = (ROLE_DEVELOPER, ROLE_INVESTOR)

# ─── The logical clock (PRD §2.4) ─────────────────────

CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Common properties (PRD §2.4) ─────────────────────

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# ─── Enumerated value sets (PRD §3) ───────────────────

DEVELOPER_STATUSES = ("ACTIVE", "SUSPENDED", "DEBARRED")
SANCTION_ACTIONS = ("SUSPEND", "REINSTATE", "DEBAR")
INVESTOR_TYPES = ("SYNDICATOR", "DIRECT_CORPORATE", "FUND")
POOL_STATUSES = ("OPEN", "OVERSUBSCRIBED", "EXHAUSTED")
DEVELOPMENT_STATUSES = (
    "PLANNING",
    "FINANCED",
    "UNDER_CONSTRUCTION",
    "PLACED_IN_SERVICE",
    "STABILIZED",
    "WITHDRAWN",
)
COMPLIANCE_STATUSES = (
    "UNRESTRICTED",
    "RESTRICTED",
    "EXTENDED_USE",
    "RELEASED",
    "NONCOMPLIANT",
)
SET_ASIDE_ELECTIONS = ("MIN_20_50", "MIN_40_60", "AVG_INCOME")
UNIT_DESIGNATIONS = ("RESTRICTED", "MARKET", "EMPLOYEE_UNIT")
UNIT_STATUSES = ("PROPOSED", "ACTIVE", "RELEASED")
ALLOCATION_STATUSES = (
    "PENDING",
    "AWARDED",
    "DENIED",
    "DEFERRED",
    "RETURNED",
    "EXPIRED",
    "COMMITTED",
    "RELEASED",
)
CAP_DECISIONS = ("AWARD", "DENY")
AGREEMENT_STATUSES = ("DRAFT", "RECORDED", "AMENDMENT_PENDING", "RELEASED")
BOND_ISSUE_STATUSES = ("DRAFT", "ISSUED", "CONVERTED", "MANDATORY_REDEEMED")
DRAW_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "FUNDED", "VOIDED")
DRAW_DECISIONS = ("APPROVE", "REJECT")
DSCR_BASES = ("T3", "T12")
COST_CERT_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION", "ACCEPTED")
COST_CERT_DECISIONS = ("ACCEPT", "RETURN")
CREDIT_ALLOCATION_STATUSES = ("PENDING", "ISSUED", "RECAPTURE_PENDING", "RECAPTURED")
DELIVERY_STATUSES = ("DELIVERED", "ACCEPTED", "RESCINDED", "RECAPTURE_FLAGGED")
COMPLIANCE_REPORT_STATUSES = ("SUBMITTED", "CLEARED", "NONCOMPLIANCE_FOUND")
COMPLIANCE_FINDINGS = ("CLEARED", "NONCOMPLIANCE")
INSPECTION_STATUSES = ("SCHEDULED", "COMPLETED", "MISSED")

ALLOWED_AMI_PERCENTS = (20, 30, 40, 50, 60, 70, 80)

# ─── Restricted rent ceiling inputs (PRD §3.2) ────────

# One hundred percent of area median annual income, in cents, by imputed
# household size.
AMI_ANNUAL_INCOME_CENTS = {
    1: 6300000,
    2: 7200000,
    3: 8100000,
    4: 9000000,
    5: 9720000,
    6: 10440000,
}

# The band cap each election imposes on a unit's own elected band.
ELECTION_BAND_CAP = {"MIN_20_50": 50, "MIN_40_60": 60, "AVG_INCOME": 80}

# The AMI band at or below which a restricted unit counts toward the set-aside.
SET_ASIDE_QUALIFYING_BAND = {"MIN_20_50": 50, "MIN_40_60": 60, "AVG_INCOME": 80}

# The set-aside ratio each election must reach, in basis points.
SET_ASIDE_THRESHOLD_BPS = {"MIN_20_50": 2000, "MIN_40_60": 4000, "AVG_INCOME": 4000}

# The average elected band ceiling that applies to AVG_INCOME only.
AVG_INCOME_AVERAGE_CEILING_BPS = 6000

RENT_FLOOR_CENTS = 25000
RENT_INCOME_SHARE_PCT = 30
MONTHS_PER_YEAR = 12

# ─── Bond sizing and arbitrage (PRD §2.5, §3.5, §3.6) ─

BPS_SCALE = 10000
ISSUANCE_ALLOWANCE_BPS = 200
NEGATIVE_ARBITRAGE_ALLOWANCE_BPS = 200
AUTHORIZED_DENOMINATION_CENTS = 500000
ARBITRAGE_DAYS_PER_YEAR = 360

# ─── Fifty-percent test and conversion (PRD §3.5, §3.7) ─

FIFTY_PERCENT_THRESHOLD_BPS = 5000
DSCR_MINIMUM_BPS = 11500
OCCUPANCY_MINIMUM_BPS = 9000
T3_WINDOW_MONTHS = 3
T3_ANNUALIZATION = 4
T12_WINDOW_MONTHS = 12
T12_ANNUALIZATION = 1

# ─── Credit (PRD §3.8) ────────────────────────────────

CREDIT_PERIOD_YEARS = 10
MAX_CREDIT_PERCENTAGE_BPS = 1000

# ─── Compliance and inspections (PRD §3.9) ────────────

MIN_AVERAGE_AMI_PERCENT = 1
MAX_AVERAGE_AMI_PERCENT = 80
INSPECTION_CYCLE_DAYS = 1095
INSPECTION_BUFFER_DAYS = 14

# ─── Term minimums (PRD §3.4) ─────────────────────────

MIN_COMPLIANCE_PERIOD_YEARS = 15
EXTENDED_USE_MINIMUM_GAP_YEARS = 15

# ─── Identifiers that resolve to nothing ──────────────

MISSING_UUID_A = "11111111-1111-4111-8111-111111111111"
MISSING_UUID_B = "22222222-2222-4222-8222-222222222222"
MISSING_UUID_C = "33333333-3333-4333-8333-333333333333"
MISSING_UUID_D = "44444444-4444-4444-8444-444444444444"
MISSING_UUID_E = "00000000-0000-4000-8000-0000000000ff"
MISSING_UUID_F = "00000000-0000-4000-8000-0000000000fe"

# ─── The canonical program-year pool ──────────────────

PROGRAM_YEAR = 2026
POOL_BASE_CAP_CENTS = 500000000
POOL_CARRYFORWARD_CENTS = 100000000
POOL_TOTAL_CAP_CENTS = POOL_BASE_CAP_CENTS + POOL_CARRYFORWARD_CENTS

# ─── The canonical sponsor and investor ───────────────

SPONSOR_NAME = "Harborview Partners"
SPONSOR_TAX_ID = "81-1000001"
SPONSOR_EMAIL = "ops@harborview.test"

SECOND_SPONSOR_NAME = "Bayside Housing Group"
SECOND_SPONSOR_TAX_ID = "81-1000002"
SECOND_SPONSOR_EMAIL = "ops@bayside.test"

INVESTOR_NAME = "Cascade Credit Fund"
INVESTOR_TAX_ID = "91-2000002"
INVESTOR_TYPE = "SYNDICATOR"

SECOND_INVESTOR_NAME = "Puget Equity Partners"
SECOND_INVESTOR_TAX_ID = "91-2000003"

# ─── The four-unit development ────────────────────────
# Two restricted two-bedrooms and two market one-bedrooms. The restricted rows
# hold half the units and half the floor space, so every fraction lands on
# exactly 5,000 basis points and the provisional fifty-percent test sits on its
# inclusive boundary.

COMPACT_PROJECT_NAME = "Harborview Annex"
COMPACT_TOTAL_UNITS = 4
COMPACT_TOTAL_FLOOR_SPACE_SQFT = 3400
COMPACT_LAND_COST_CENTS = 40000000
COMPACT_DEPRECIABLE_BASIS_CENTS = 360000000
COMPACT_AGGREGATE_BASIS_CENTS = COMPACT_LAND_COST_CENTS + COMPACT_DEPRECIABLE_BASIS_CENTS

# ─── The ten-unit development ─────────────────────────
# Four restricted units carrying 3,350 of 8,500 square feet, so the floor-space
# fraction (3,941 bps) is strictly smaller than the unit fraction (4,000 bps)
# and the applicable fraction has to pick the smaller of the two.

TEN_UNIT_PROJECT_NAME = "Harborview Commons"
TEN_UNIT_TOTAL_UNITS = 10
TEN_UNIT_TOTAL_FLOOR_SPACE_SQFT = 8500
TEN_UNIT_LAND_COST_CENTS = 40000000
TEN_UNIT_DEPRECIABLE_BASIS_CENTS = 360000000
TEN_UNIT_AGGREGATE_BASIS_CENTS = (
    TEN_UNIT_LAND_COST_CENTS + TEN_UNIT_DEPRECIABLE_BASIS_CENTS
)

# ─── The canonical agreement terms ────────────────────

COMPLIANCE_PERIOD_YEARS = 15
EXTENDED_USE_YEARS = 30
RECORDING_COUNTY = "King"
INSTRUMENT_NUMBER = "KC-2026-0001"

# ─── The canonical cap request and award ──────────────

REQUESTED_AMOUNT_CENTS = 200000000
REQUESTED_CLOSING_DATE = "2026-09-15T00:00:00Z"
AWARDED_AMOUNT_CENTS = 200000000
AWARD_EXPIRY_DATE = "2027-06-30T00:00:00Z"

# ─── The canonical bond issue ─────────────────────────
# 190,000,000 of eligible cost plus 6,000,000 of capitalized interest gives a
# provisional par of 196,000,000, a 3,920,000 issuance allowance and an unrounded
# par of 199,920,000 — which the denomination step lifts to exactly 200,000,000,
# the awarded amount to the cent.

ELIGIBLE_COST_CENTS = 190000000
CAPITALIZED_INTEREST_CENTS = 6000000
BOND_YIELD_BPS = 450
INVESTMENT_YIELD_BPS = 200
ISSUANCE_ALLOWANCE_CENTS = 3920000
PAR_AMOUNT_CENTS = 200000000
NEGATIVE_ARBITRAGE_ALLOWANCE_CENTS = 4000000
CLOSING_DATE = "2026-09-15T00:00:00Z"

# ─── The canonical construction draw ──────────────────

DRAW_PERIOD_START = "2026-09-15T00:00:00Z"
DRAW_PERIOD_END = "2026-11-15T00:00:00Z"
DRAW_AMOUNT_CENTS = 200000000

# ─── The canonical operating months and conversion ────

MONTH_NOI_CENTS = 18000000
MONTH_DEBT_SERVICE_CENTS = 15000000
CONVERSION_DATE = "2027-03-01T00:00:00Z"

# ─── The canonical cost certification ─────────────────

CERTIFIED_LAND_COST_CENTS = 40000000
CERTIFIED_DEPRECIABLE_BASIS_CENTS = 360000000
CERTIFIED_ELIGIBLE_BASIS_CENTS = 355000000
CERTIFIED_AGGREGATE_BASIS_CENTS = (
    CERTIFIED_LAND_COST_CENTS + CERTIFIED_DEPRECIABLE_BASIS_CENTS
)
PREPARER_NAME = "Nolan CPA"

# ─── The canonical credit allocation and delivery ─────

CREDIT_PERCENTAGE_BPS = 400
PLACED_IN_SERVICE_DATE = "2026-08-01T00:00:00Z"
FORM_8609_NUMBER = "8609-2026-0001"
