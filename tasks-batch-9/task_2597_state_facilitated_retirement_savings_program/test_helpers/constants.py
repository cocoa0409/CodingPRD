"""
Canonical payloads, enum vocabularies and documented defaults.

Money is always whole cents and every rate is always basis points, so nothing in
this module carries a floating-point amount. The program-year dial defaults
below are the values the API materialises when a program year is created without
naming them.
"""

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# The instant a freshly started service reports before anybody moves the clock.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Instants the scenarios in this suite anchor on.
CLOCK_2026_01_01 = "2026-01-01T00:00:00Z"
CLOCK_2026_02_01 = "2026-02-01T00:00:00Z"
CLOCK_2026_03_06 = "2026-03-06T00:00:00Z"
CLOCK_2026_04_05 = "2026-04-05T00:00:00Z"
CLOCK_2026_05_01 = "2026-05-01T00:00:00Z"
CLOCK_2026_07_01 = "2026-07-01T00:00:00Z"
CLOCK_2027_01_01 = "2027-01-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Program-year dials
# ---------------------------------------------------------------------------
PROGRAM_YEAR_2026: Dict[str, Any] = {
    "calendar_year": 2026,
    "ira_annual_limit_cents": 700000,
    "default_contribution_rate_bp": 500,
}

PROGRAM_YEAR_2027: Dict[str, Any] = {
    "calendar_year": 2027,
    "ira_annual_limit_cents": 700000,
    "default_contribution_rate_bp": 500,
}

# Values the API supplies for every optional dial left unnamed at creation.
PROGRAM_YEAR_DEFAULTS: Dict[str, Any] = {
    "catch_up_limit_cents": 100000,
    "escalation_increment_bp": 100,
    "escalation_cap_bp": 800,
    "escalation_seasoning_days": 180,
    "opt_out_window_days": 30,
    "remittance_due_days": 7,
    "notice_period_days": 90,
    "sustained_notice_days": 180,
    "register_penalty_initial_cents_per_employee": 25000,
    "register_penalty_sustained_cents_per_employee": 50000,
    "remit_penalty_monthly_rate_bp": 150,
    "remit_penalty_floor_cents": 10000,
    "remit_penalty_cap_bp": 5000,
    "nia_daily_rate_bp": 2,
    "correction_deadline_month_day": "04-15",
}

# Contribution-rate band the API enforces on an elected deferral rate.
RATE_MIN_BP = 100
RATE_MAX_BP = 1500

# Allocation weights always sum to exactly this many basis points.
ALLOCATION_TOTAL_BP = 10000

# ---------------------------------------------------------------------------
# Fund menu
# ---------------------------------------------------------------------------
FUND_TDF2045: Dict[str, Any] = {
    "fund_code": "TDF2045",
    "name": "Target Retirement 2045",
    "category": "TARGET_DATE",
    "target_year": 2045,
    "expense_ratio_bp": 30,
    "default_eligible": True,
}

FUND_TDF2040: Dict[str, Any] = {
    "fund_code": "TDF2040",
    "name": "Target Retirement 2040",
    "category": "TARGET_DATE",
    "target_year": 2040,
    "expense_ratio_bp": 32,
    "default_eligible": True,
}

FUND_TDF2050: Dict[str, Any] = {
    "fund_code": "TDF2050",
    "name": "Target Retirement 2050",
    "category": "TARGET_DATE",
    "target_year": 2050,
    "expense_ratio_bp": 28,
    "default_eligible": True,
}

FUND_MMKT01: Dict[str, Any] = {
    "fund_code": "MMKT01",
    "name": "Government Money Market",
    "category": "CAPITAL_PRESERVATION",
    "expense_ratio_bp": 20,
    "default_eligible": True,
}

FUND_EQIDX1: Dict[str, Any] = {
    "fund_code": "EQIDX1",
    "name": "Total Equity Index",
    "category": "EQUITY_INDEX",
    "expense_ratio_bp": 12,
    "default_eligible": False,
}

FUND_BNDIDX: Dict[str, Any] = {
    "fund_code": "BNDIDX",
    "name": "Aggregate Bond Index",
    "category": "BOND_INDEX",
    "expense_ratio_bp": 15,
    "default_eligible": False,
}

# The two-fund menu the majority of scenarios stand up.
DEFAULT_FUND_MENU: List[Dict[str, Any]] = [FUND_TDF2045, FUND_MMKT01]

# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------
# 60 employees: inside the 50..99 band.
EMPLOYER_DELTA: Dict[str, Any] = {
    "ein": "12-3456789",
    "legal_name": "Delta Fabrication LLC",
    "worksite_state": "CA",
    "employee_count": 60,
}

# 5 employees: the smallest headcount the mandate still covers.
EMPLOYER_HARBOR: Dict[str, Any] = {
    "ein": "44-5556660",
    "legal_name": "Harbor Micro Foods LLC",
    "worksite_state": "CA",
    "employee_count": 5,
}

# 4 employees: one below the mandate floor.
EMPLOYER_ORCHARD: Dict[str, Any] = {
    "ein": "55-6667770",
    "legal_name": "Orchard Lane Bindery LLC",
    "worksite_state": "CA",
    "employee_count": 4,
}

# 120 employees: inside the largest band.
EMPLOYER_RIDGE: Dict[str, Any] = {
    "ein": "77-8889990",
    "legal_name": "Ridge Composites Inc",
    "worksite_state": "CA",
    "employee_count": 120,
}

EMPLOYER_SECOND: Dict[str, Any] = {
    "ein": "22-3334440",
    "legal_name": "Brightwater Signage LLC",
    "worksite_state": "CA",
    "employee_count": 60,
}

REGISTRATION_DELTA: Dict[str, Any] = {
    "non_fiduciary_acknowledged": True,
    "payroll_contact_email": "payroll@delta.example",
}

REGISTRATION_GENERIC: Dict[str, Any] = {
    "non_fiduciary_acknowledged": True,
    "payroll_contact_email": "payroll@employer.example",
}

# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
# Born 1980, so the retirement year is 2045.
PARTICIPANT_ROSA: Dict[str, Any] = {
    "full_name": "Rosa Lim",
    "date_of_birth": "1980-05-10",
    "email": "rosa.lim@x.example",
    "ssn_last4": "1234",
    "state_resident": True,
}

# Born 1975, so the retirement year is 2040.
PARTICIPANT_TOMAS: Dict[str, Any] = {
    "full_name": "Tomas Reed",
    "date_of_birth": "1975-03-22",
    "email": "tomas.reed@x.example",
    "ssn_last4": "5678",
    "state_resident": True,
}

PARTICIPANT_ANA: Dict[str, Any] = {
    "full_name": "Ana Beltran",
    "date_of_birth": "1990-09-01",
    "email": "ana.beltran@x.example",
    "ssn_last4": "9012",
    "state_resident": True,
}

# Turns 50 or older inside program year 2026, so catch-up applies.
PARTICIPANT_MARGO: Dict[str, Any] = {
    "full_name": "Margo Estes",
    "date_of_birth": "1970-02-14",
    "email": "margo.estes@x.example",
    "ssn_last4": "3456",
    "state_resident": True,
}

# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
ENROLLMENT_ROSA: Dict[str, Any] = {
    "hire_date": "2026-01-05",
    "annual_compensation_cents": 9600000,
}

# ---------------------------------------------------------------------------
# Exemption certification
# ---------------------------------------------------------------------------
EXEMPTION_401K: Dict[str, Any] = {
    "qualified_plan_type": "401K",
    "plan_sponsor_ein": "99-1112223",
    "plan_effective_date": "2026-01-01",
    "attestation_accepted": True,
}

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
FUND_CATEGORIES = ["TARGET_DATE", "CAPITAL_PRESERVATION", "EQUITY_INDEX", "BOND_INDEX"]
FUND_STATUSES = ["OPEN", "CLOSED_TO_NEW", "TERMINATED"]
WAVE_TIERS = ["WAVE_1", "WAVE_2", "WAVE_3", "NOT_COVERED"]
REGISTRATION_STATUSES = [
    "PENDING_REGISTRATION", "REGISTERED", "EXEMPT_CERTIFIED", "EXEMPT_SMALL",
]
COMPLIANCE_STATUSES = ["COMPLIANT", "DELINQUENT", "PENALIZED", "REFERRED"]
QUALIFIED_PLAN_TYPES = ["401K", "403B", "SIMPLE_IRA", "SEP_IRA", "DEFINED_BENEFIT"]
EXEMPTION_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED", "REVOKED"]
EXEMPTION_DECISIONS = ["APPROVE", "REJECT"]
RATE_SOURCES = ["DEFAULT", "PARTICIPANT_ELECTED", "ESCALATED"]
ENROLLMENT_STATUSES = ["NOTIFIED", "ACTIVE", "OPTED_OUT", "TERMINATED"]
OPT_OUT_REASON_CODES = ["NOT_INTERESTED", "HAS_OTHER_PLAN", "AFFORDABILITY", "OTHER"]
ACCOUNT_TYPES = ["ROTH_IRA", "TRADITIONAL_IRA"]
ACCOUNT_STATUSES = ["OPEN", "CLOSURE_PENDING", "CLOSED"]
POSTURES = ["UNRESTRICTED", "RESTRICTED", "LOCKED"]
CLOSURE_REASONS = [
    "PARTICIPANT_REQUEST", "ROLLOVER_OUT", "DECEASED", "PROGRAM_ACTION",
]
RESIDUAL_DISPOSITIONS = ["ROLLOVER_OUT", "CASH_DISTRIBUTION"]
ELECTION_SOURCES = ["SYSTEM_DEFAULT", "PARTICIPANT_ELECTED"]
ELECTION_STATUSES = ["ACTIVE", "SUPERSEDED"]
SELECTION_BASES = ["TARGET_DATE_GLIDE_PATH", "CAPITAL_PRESERVATION_FALLBACK"]
REMITTANCE_STATUSES = ["DRAFT", "SUBMITTED", "POSTED", "REJECTED", "REVERSED"]
REMITTANCE_LINE_STATUSES = ["PENDING", "POSTED", "REVERSED", "RETURNED"]
NIA_METHODS = ["ADJUSTED_BALANCE", "DAILY_PRORATA"]
CORRECTION_METHODS = [
    "REFUND_TO_PARTICIPANT", "RECHARACTERIZE_TO_TRADITIONAL", "CARRY_FORWARD",
]
EXCESS_CASE_STATUSES = ["DETECTED", "METHOD_ELECTED", "COMPLETED", "EXPIRED", "VOIDED"]
VIOLATION_TYPES = ["FAILURE_TO_REGISTER", "FAILURE_TO_REMIT", "FAILURE_TO_ENROLL"]
PENALTY_STATUSES = ["ASSESSED", "ABATED", "AFFIRMED"]
PENALTY_ORIGINS = ["MANUAL", "SYSTEM_CASCADE", "SWEEP"]
PENALTY_DISPOSITIONS = ["AFFIRM", "ABATE"]
REFERRAL_AGENCIES = [
    "STATE_LABOR_COMMISSIONER", "STATE_TAX_AUTHORITY", "ATTORNEY_GENERAL",
]
REFERRAL_STATUSES = ["OPEN", "WITHDRAWN"]
DESTINATION_TYPES = ["EXTERNAL_IRA", "PROGRAM_ACCOUNT"]
TRANSFER_KINDS = ["DIRECT_ROLLOVER", "TRUSTEE_TO_TRUSTEE", "INDIRECT_60_DAY"]
TRANSFER_STATUSES = ["REQUESTED", "SETTLED", "RETURNED", "FAILED_TAXABLE"]

# ---------------------------------------------------------------------------
# Wave bands
# ---------------------------------------------------------------------------
WAVE_1_DEADLINE = "2026-06-30"
WAVE_2_DEADLINE = "2026-12-31"
WAVE_3_DEADLINE = "2027-06-30"

# ---------------------------------------------------------------------------
# Portability fee tiers, in basis points keyed on the gross amount
# ---------------------------------------------------------------------------
PORTABILITY_FEE_BP_LOW = 40      # gross of 500000 cents or less
PORTABILITY_FEE_BP_MID = 50      # gross 500001 through 950000 cents inclusive
PORTABILITY_FEE_BP_HIGH = 60     # gross 950001 cents or more
INDIRECT_WITHHOLDING_BP = 1000   # ten per cent of the taxable portion
INDIRECT_SETTLE_BY_DAYS = 60
INDIRECT_WINDOW_DAYS = 365

# ---------------------------------------------------------------------------
# Excess correction
# ---------------------------------------------------------------------------
EXCISE_TAX_BP = 600
