"""Domain constants. Every figure here is taken literally from PRD.md / SCAFFOLD.yaml."""
from decimal import Decimal

# --- federal anchors (PRD 2.6) ------------------------------------------------
FEDERAL_MIN_WEEKLY_SALARY_CENTS = 84400
FEDERAL_HCE_ANNUAL_CENTS = 13200000
FEDERAL_PRIMARY_DUTY_MIN_PCT = Decimal("50.0")
STRICT_ENUM_DUTY_FLOOR_PCT = Decimal("60.0")
HCE_MIN_DUTY_PCT = Decimal("20.0")
COMPUTER_HOURLY_MIN_CENTS = 2763
EXECUTIVE_MIN_SUPERVISED = 2
ANNUAL_HOURS_DIVISOR = 2080
STANDARD_WORKWEEK_HOURS = Decimal(40)

# --- duties corroboration ----------------------------------------------------
CORROBORATION_SPREAD_MAX_PCT = Decimal("15.0")
MANAGER_WEIGHT_PCT = Decimal(40)
INCUMBENT_WEIGHT_PCT = Decimal(60)

# --- back wage --------------------------------------------------------------
LOOKBACK_WEEKS_STANDARD = 104
LOOKBACK_WEEKS_WILLFUL = 156

# --- risk scoring -----------------------------------------------------------
MISCLASSIFICATION_STATUS_RISK = 25
SCREENING_UNCERTAINTY_PREMIUM = 12

# --- fiscal / scheduling ----------------------------------------------------
VOLUNTARY_CORRECTION_MANDATORY_CENTS = 5000000
LEGAL_COUNSEL_AUTHORITY_CAP_CENTS = 25000000
RECLASS_WINDOW_BUFFER_DAYS = 7
MAX_CONCURRENT_RECLASS_PER_FAMILY = 3
REANALYSIS_DUTY_DELTA_PCT = Decimal("10.0")

# --- enums ------------------------------------------------------------------
ROLES = [
    "ProgramAdmin",
    "ComplianceAnalyst",
    "ClassificationReviewer",
    "CompensationManager",
    "EmployeeRelationsLead",
    "LegalCounsel",
    "Auditor",
]
ALL_ROLES = list(ROLES)

LOOKBACK_POLICIES = ["STANDARD_2Y", "WILLFUL_3Y"]
PROJECT_STATUSES = ["PLANNING", "FIELDWORK", "REMEDIATION", "CLOSED"]
DUTIES_TEST_VARIANTS = ["FEDERAL", "QUANTITATIVE_50PCT", "STRICT_ENUM"]
IC_TESTS = ["ABC", "ECONOMIC_REALITY", "COMMON_LAW"]
FLS_STATUSES = ["EXEMPT", "NONEXEMPT"]
CLAIMED_EXEMPTION_TESTS = [
    "EXECUTIVE",
    "ADMINISTRATIVE",
    "PROFESSIONAL",
    "COMPUTER",
    "OUTSIDE_SALES",
    "NONE",
]
APPLIED_TESTS = [
    "EXECUTIVE",
    "ADMINISTRATIVE",
    "PROFESSIONAL",
    "COMPUTER",
    "OUTSIDE_SALES",
]
SALARY_BASES = ["SALARY", "HOURLY", "FEE", "COMMISSION"]
DISCRETION_LEVELS = ["NONE", "ROUTINE", "INDEPENDENT_JUDGMENT"]
RESPONDENT_TYPES = ["MANAGER", "INCUMBENT"]
CONVERSION_METHODS = ["SALARY_DIV_2080", "COST_NEUTRAL_WITH_OT"]
BACK_WAGE_METHODS = ["HALF_TIME", "FULL_RATE"]
CORRECTION_DECISIONS = [
    "SELF_CORRECT_FULL",
    "SELF_CORRECT_PARTIAL",
    "DEFER",
    "AGENCY_SUPERVISED",
]
DISPOSITIONS = ["APPROVE", "REJECT"]
COMMUNICATION_ACTIONS = ["SEND_NOTICE", "ACKNOWLEDGE", "ESCALATE"]
TRIGGER_TYPES = [
    "SALARY_CHANGE",
    "DUTIES_CHANGE",
    "REPORTING_CHANGE",
    "STATE_CHANGE",
    "FLSA_THRESHOLD_UPDATE",
]

ECONOMIC_REALITY_KEYS = [
    "control_by_worker",
    "opportunity_for_profit_or_loss",
    "worker_investment",
    "relationship_is_project_based",
    "skill_and_initiative",
    "not_integral_to_business",
]
