"""
Business constants for the De Novo Bank Charter Application API.

Every value here is stated in the PRD; nothing is invented. Grouped by the
PRD section that states it so a failing assertion can be traced back to prose.
"""

# ---------------------------------------------------------------------------
# Service mount point (PRD 2 / 4)
# ---------------------------------------------------------------------------
BASE_PREFIX = "/de-novo"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Organizing group / management fitness (PRD 3.1)
# ---------------------------------------------------------------------------
MIN_ORGANIZERS_FOR_COMPOSITION = 5
MIN_INDEPENDENT_ORGANIZERS = 3
KEY_OFFICER_ROLES = ("PROPOSED_CEO", "PROPOSED_CFO", "PROPOSED_CRO", "PROPOSED_CCO")
EXPERIENCE_WEIGHT_PCT = 40
REGULATORY_WEIGHT_PCT = 35
INTEGRITY_WEIGHT_PCT = 25
BANKING_YEARS_CAP = 20
MIN_BANKING_YEARS = 0
MAX_BANKING_YEARS = 60
MIN_REGULATORY_EXPERIENCE_SCORE = 0
MAX_REGULATORY_EXPERIENCE_SCORE = 100
MIN_QUALIFYING_SUBSCORE = 50
MIN_MANAGEMENT_COMPOSITE_SCORE = 70.00
EMPTY_MANAGEMENT_COMPOSITE_SCORE = 0.00
MIN_WAIVER_RATIONALE_LENGTH = 20
NON_WAIVABLE_FINDING_TYPE = "FINANCIAL_CRIME"

# ---------------------------------------------------------------------------
# Business plan and stress overlays (PRD 3.2)
# ---------------------------------------------------------------------------
MIN_OPENING_TIER1_CAPITAL_CENTS = 2_000_000_000
MIN_PROJECTED_BRANCH_COUNT = 1
MIN_CREDIT_LOSS_RATE_BPS = 0
MAX_CREDIT_LOSS_RATE_BPS = 5000
MIN_NIM_COMPRESSION_BPS = 0
MAX_NIM_COMPRESSION_BPS = 2000
BPS_DENOMINATOR = 10000

# ---------------------------------------------------------------------------
# Capital adequacy (PRD 3.2 / 3.3)
# ---------------------------------------------------------------------------
DE_NOVO_LEVERAGE_FLOOR_BPS = 800
BASE_REQUIRED_BPS_NATIONAL = 800
BASE_REQUIRED_BPS_STATE_MEMBER = 850
BASE_REQUIRED_BPS_STATE_NONMEMBER = 900
REQUIRED_LEVERAGE_CEILING_BPS = 1200
CONCENTRATION_TRIP_POINT_BPS = 6500
CONCENTRATION_ADD_ON_STEP_BPS = 10
CONCENTRATION_ADD_ON_CHARGE_BPS = 5
BREACH_RISK_ADD_ON_BPS = 25

# ---------------------------------------------------------------------------
# Capital raise, escrow and the release waterfall (PRD 3.4)
# ---------------------------------------------------------------------------
REIMBURSEMENT_CAP_PCT = 5

# ---------------------------------------------------------------------------
# Filings and the information-request cycle (PRD 3.5)
# ---------------------------------------------------------------------------
MAX_INFO_REQUEST_ROUNDS = 3

# ---------------------------------------------------------------------------
# Conditions of approval (PRD 3.6)
# ---------------------------------------------------------------------------
MIN_EVIDENCE_REFERENCE_LENGTH = 20
MAX_CONDITION_CODE_LENGTH = 40

# ---------------------------------------------------------------------------
# Vendors and conversion windows (PRD 3.7)
# ---------------------------------------------------------------------------
MIN_CRITICAL_DUE_DILIGENCE_SCORE = 70
MIN_CONTRACT_TERM_MONTHS = 1
MAX_CONTRACT_TERM_MONTHS = 120
MAX_WINDOW_DURATION_HOURS = 72.00
SECONDS_PER_HOUR = 3600
CONVERSION_CAPACITY = 2

# ---------------------------------------------------------------------------
# Readiness examination (PRD 3.8)
# ---------------------------------------------------------------------------
EXAM_BUFFER_HOURS = 48
EXAM_CAPACITY_PER_GROUP = 1
MAX_FINDINGS_FOR_PASS = 3

# ---------------------------------------------------------------------------
# Heightened supervision (PRD 3.9)
# ---------------------------------------------------------------------------
SECONDS_PER_DAY = 86400
DAYS_PER_SUPERVISION_YEAR = 365
SUPERVISION_WINDOW_DAYS = 1095
MIN_SUPERVISION_YEAR_INDEX = 1
MAX_SUPERVISION_YEAR_INDEX = 3
DEVIATION_APPROVAL_THRESHOLD_BPS = 1000
DEVIATION_ESCALATION_THRESHOLD_BPS = 2500
ZERO_BASELINE_DEVIATION_BPS = 2500
MIN_NARRATIVE_LENGTH = 20
MAX_NARRATIVE_LENGTH = 500
