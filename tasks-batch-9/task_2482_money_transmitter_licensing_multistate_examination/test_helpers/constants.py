"""Domain constants, thresholds and seed reference data from the PRD.

Every number here is transcribed from PRD prose: the surety bond tiers and class
multipliers of section 3.4, the coverage haircuts and posture bands of section
3.7, the renewal fee tiers of section 3.5, the oversight weights of section 3.6
and the deadlines that the logical clock of section 2.4 measures.
"""

from datetime import datetime, timedelta
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

API_PREFIX = ""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_LICENSING_MANAGER = "LicensingManager"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_CHIEF_COMPLIANCE_OFFICER = "ChiefComplianceOfficer"
ROLE_STATE_REGULATOR = "StateRegulator"
ROLE_DELEGATE_OPERATOR = "DelegateOperator"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_LICENSING_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CHIEF_COMPLIANCE_OFFICER,
    ROLE_STATE_REGULATOR,
    ROLE_DELEGATE_OPERATOR,
)

# ---------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

SEED_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Audit stamps (PRD 2.4)
# ---------------------------------------------------------------------------

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_ROW_FIELDS = ("id", "created_at")
IMMUTABLE_ROW_ABSENT_FIELDS = ("updated_at", "version")

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Surety bond requirement (PRD 3.4)
# ---------------------------------------------------------------------------

VOLUME_TIER_1_MAX_CENTS = 1_000_000_000
VOLUME_TIER_2_MAX_CENTS = 10_000_000_000
TIER_1_BOND_CENTS = 2_500_000
TIER_2_BOND_CENTS = 10_000_000
TIER_3_BOND_CENTS = 25_000_000

CLASS_MULTIPLIER_BPS: Dict[str, int] = {
    "MONEY_TRANSMISSION": 10_000,
    "PAYMENT_INSTRUMENTS": 12_000,
    "VIRTUAL_CURRENCY": 15_000,
}

# ---------------------------------------------------------------------------
# Permissible investment coverage (PRD 3.7)
# ---------------------------------------------------------------------------

HAIRCUT_BPS: Dict[str, int] = {
    "CASH": 0,
    "US_TREASURY": 200,
    "MONEY_MARKET_FUND": 300,
    "AGENCY_BOND": 500,
    "RECEIVABLE_FROM_DELEGATE": 1000,
}
NON_PERMISSIBLE_ASSET_CLASSES = ("CORPORATE_DEBT",)
CONCENTRATION_CAPPED_CLASSES = (
    "AGENCY_BOND",
    "MONEY_MARKET_FUND",
    "RECEIVABLE_FROM_DELEGATE",
)
UNCAPPED_CLASSES = ("CASH", "US_TREASURY")
CONCENTRATION_CAP_BPS = 1000
RECEIVABLE_MAX_AGE_DAYS = 5

COVERAGE_PASS_BPS = 10_000
COVERAGE_WATCH_FLOOR_BPS = 9_500
FROZEN_FAILED_TEST_COUNT = 2
CERTIFICATION_WINDOW_DAYS = 45

# ---------------------------------------------------------------------------
# Control chain (PRD 3.2)
# ---------------------------------------------------------------------------

CONTROL_THRESHOLD_BPS = 2500
OFFICER_TITLES = ("CEO", "CFO", "COO", "CCO")
NON_OFFICER_TITLES = ("DIRECTOR", "ENTITY_HOLDER", "PASSIVE_INVESTOR")
MAX_CONTROL_CHAIN_DEPTH = 5
MAX_OWNERSHIP_BPS = 10_000

# ---------------------------------------------------------------------------
# Applications (PRD 3.3)
# ---------------------------------------------------------------------------

DEFICIENCY_DEADLINE_DAYS = 30
MAX_DEFICIENCY_ROUNDS = 3

# ---------------------------------------------------------------------------
# Delegates (PRD 3.6)
# ---------------------------------------------------------------------------

OVERSIGHT_TRAINING_WEIGHT_BPS = 4000
OVERSIGHT_AML_WEIGHT_BPS = 3500
OVERSIGHT_RECORDKEEPING_WEIGHT_BPS = 2500
OVERSIGHT_MIN_SCORE = 70

# ---------------------------------------------------------------------------
# Reporting calendar (PRD 3.5)
# ---------------------------------------------------------------------------

CALL_REPORT_DUE_DAYS = 45
RENEWAL_PER_DELEGATE_CENTS = 25_000
RENEWAL_TIER_1_MAX_SUBTOTAL_CENTS = 100_000
RENEWAL_TIER_2_MAX_SUBTOTAL_CENTS = 250_000
RENEWAL_TIER_1_BPS = 500
RENEWAL_TIER_2_BPS = 350
RENEWAL_TIER_3_BPS = 200

# ---------------------------------------------------------------------------
# Bonds, exams, information requests and enforcement deadlines
# ---------------------------------------------------------------------------

BOND_NOTICE_MIN_DAYS = 30
EXAM_COOLING_OFF_DAYS = 30
EXAM_FINDINGS_BLOCKING_THRESHOLD = 3
INFO_REQUEST_REOPEN_DAYS = 5
ENFORCEMENT_RESPONSE_WINDOW_DAYS = 20

# ---------------------------------------------------------------------------
# Enumerations (PRD 2.8, 3.1 - 3.9)
# ---------------------------------------------------------------------------

LICENSE_CLASSES = ("MONEY_TRANSMISSION", "PAYMENT_INSTRUMENTS", "VIRTUAL_CURRENCY")
CALL_REPORT_FREQUENCIES = ("QUARTERLY", "ANNUAL")
ASSET_CLASSES = (
    "CASH",
    "US_TREASURY",
    "AGENCY_BOND",
    "MONEY_MARKET_FUND",
    "RECEIVABLE_FROM_DELEGATE",
    "CORPORATE_DEBT",
)
COVERAGE_METHODS = ("BOOK_VALUE", "ELIGIBLE_MARKET")
ENFORCEMENT_BASES = (
    "PERMISSIBLE_INVESTMENT_SHORTFALL",
    "BOND_LAPSE",
    "DELINQUENT_REPORTING",
    "UNAUTHORIZED_DELEGATE",
    "EXAM_FINDING",
)

# ---------------------------------------------------------------------------
# Seed jurisdiction configurations
# ---------------------------------------------------------------------------

CA_CONFIG: Dict[str, Any] = {
    "state_code": "CA",
    "name": "California DFPI",
    "min_net_worth_cents": 50_000_000,
    "base_bond_cents": 5_000_000,
    "per_delegate_bond_cents": 100_000,
    "bond_cap_cents": 40_000_000,
    "response_window_days": 15,
    "renewal_fee_cents": 500_000,
    "assessment_rate_bps": 25,
    "call_report_frequency": "QUARTERLY",
    "participates_in_multistate": True,
}

TX_CONFIG: Dict[str, Any] = {
    "state_code": "TX",
    "name": "Texas DOB",
    "min_net_worth_cents": 100_000_000,
    "base_bond_cents": 30_000_000,
    "per_delegate_bond_cents": 250_000,
    "bond_cap_cents": 60_000_000,
    "response_window_days": 10,
    "renewal_fee_cents": 750_000,
    "assessment_rate_bps": 40,
    "call_report_frequency": "QUARTERLY",
    "participates_in_multistate": True,
}

NV_CONFIG: Dict[str, Any] = {
    "state_code": "NV",
    "name": "Nevada FID",
    "min_net_worth_cents": 10_000_000,
    "base_bond_cents": 1_000_000,
    "per_delegate_bond_cents": 50_000,
    "bond_cap_cents": 20_000_000,
    "response_window_days": 30,
    "renewal_fee_cents": 245_000,
    "assessment_rate_bps": 10,
    "call_report_frequency": "ANNUAL",
    "participates_in_multistate": False,
}

# ---------------------------------------------------------------------------
# Seed licensee / delegate values
# ---------------------------------------------------------------------------

SEED_LICENSEE_NAME = "Meridian Transfer LLC"
SEED_LICENSEE_EIN = "741100001"
SEED_NET_WORTH_CENTS = 500_000_000
SEED_NET_WORTH_STATEMENT_DATE = "2026-06-30T00:00:00Z"
SEED_NARRATIVE = "Domestic P2P transfers."
SEED_BOND_ISSUER = "Atlas Surety"
SEED_DELEGATE_NAME = "Sunrise Checks Inc"
SEED_SECOND_DELEGATE_NAME = "Harbor Wire Agents LLC"
SEED_MONTHLY_CAP_CENTS = 5_000_000


# ---------------------------------------------------------------------------
# Instant arithmetic on the logical clock (PRD 2.4: exact 24-hour multiples)
# ---------------------------------------------------------------------------

def iso_add_days(instant: str, days: int) -> str:
    """Add exact twenty-four-hour periods to an ISO 8601 UTC instant."""
    base = datetime.strptime(instant.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    return (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
