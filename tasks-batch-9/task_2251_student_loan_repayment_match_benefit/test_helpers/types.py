"""
TypedDict shapes and enum constants for the Student Loan Repayment Match
Benefit API.

Every resource shape below mirrors the PRD's resource declarations exactly.
Per PRD §2.4, ten collections carry the full common-field set
(`id`, `created_at`, `updated_at`, `version`) while four append-only audit
rows carry only `id` and `created_at` — for those four, `updated_at` and
`version` are absent from the resource entirely, so they are deliberately
omitted from the TypedDicts here rather than typed as optional.
"""

from typing import List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

BENEFITS_ADMINISTRATOR = "BenefitsAdministrator"
EMPLOYEE = "Employee"
PAYROLL_OPERATOR = "PayrollOperator"
RECORDKEEPER = "Recordkeeper"
COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES: List[str] = [
    BENEFITS_ADMINISTRATOR,
    EMPLOYEE,
    PAYROLL_OPERATOR,
    RECORDKEEPER,
    COMPLIANCE_AUDITOR,
]

# ---------------------------------------------------------------------------
# Status vocabularies (PRD §3)
# ---------------------------------------------------------------------------

PLAN_YEAR_STATUSES = ["DRAFT", "OPEN", "LOCKED", "CLOSED"]
AMENDMENT_STATUSES = ["DRAFTED", "ADOPTED", "NOTICE_SENT", "EFFECTIVE", "RESCINDED"]
NOTICE_CHANNELS = ["EMAIL", "MAIL", "PORTAL"]
EMPLOYMENT_STATUSES = ["ACTIVE", "LEAVE_UNPAID", "LEAVE_PAID", "TERMINATED", "REHIRED"]
EMPLOYMENT_EVENT_TYPES = ["TERMINATE", "REHIRE"]
LEAVE_TYPES = ["UNPAID", "PAID_FMLA", "MILITARY"]
PAYROLL_PERIOD_STATUSES = ["OPEN", "CLOSED", "FUNDED"]
LOAN_ACCOUNT_STATUSES = ["UNVERIFIED", "VERIFIED", "DISQUALIFIED"]
CERTIFICATION_METHODS = ["SELF_CERTIFICATION", "SERVICER_STATEMENT"]
CERTIFICATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "RETURNED",
    "ACCEPTED",
    "AUDIT_HOLD",
    "VOIDED",
    "SUPERSEDED",
]
CERTIFICATION_DECISIONS = ["ACCEPT", "RETURN"]
AUDIT_RELEASE_RESOLUTIONS = ["CLEAR", "VOID"]
ALLOCATION_TYPES = ["MIRROR", "TRUE_UP"]
FUNDING_STATUSES = ["UNFUNDED", "SCHEDULED", "FUNDED", "REVERSED"]
VESTING_STATUSES = ["UNVESTED", "PARTIALLY_VESTED", "FULLY_VESTED", "FORFEITED"]
FUNDING_BATCH_STATUSES = ["PENDING", "TRANSMITTED", "SETTLED", "REJECTED"]
SETTLEMENT_OUTCOMES = ["SETTLED", "REJECTED"]
FORFEITURE_REASON_CODES = ["TERMINATION_UNVESTED", "TERMINATION_PARTIAL_VESTING"]
CORRECTION_REASON_CODES = [
    "ERRONEOUS_MATCH",
    "CERTIFICATION_VOID",
    "TRUE_UP_RECOUPMENT",
    "ACP_CORRECTIVE_FORFEITURE",
]
TEST_METHODS = ["CURRENT_YEAR", "PRIOR_YEAR"]
TEST_STATUSES = ["PENDING", "PASSED", "FAILED", "CORRECTED", "STALE"]
CORRECTION_METHODS = ["QNEC", "CORRECTIVE_FORFEITURE"]

# Collections that carry the full common-field set (PRD §2.4).
VERSIONED_COLLECTIONS = [
    "PlanYear",
    "PlanAmendment",
    "Employee",
    "PayrollPeriod",
    "ContributionRecord",
    "LoanAccount",
    "LoanCertification",
    "MatchAllocation",
    "FundingBatch",
    "NondiscriminationTest",
]

# Append-only audit rows: `id` and `created_at` only (PRD §2.4).
APPEND_ONLY_COLLECTIONS = [
    "LeaveEvent",
    "CertificationLine",
    "ForfeitureRecord",
    "CorrectionAdjustment",
]


# ---------------------------------------------------------------------------
# Versioned resources — id / created_at / updated_at / version
# ---------------------------------------------------------------------------


class PlanYear(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    year: int
    status: str
    period_start: str
    period_end: str
    certification_window_open: str
    certification_deadline: str
    compensation_cap_cents: int
    annual_deferral_limit_cents: int
    hce_prior_comp_threshold_cents: int
    tier1_pct: float
    tier1_match_rate: float
    tier2_pct: float
    tier2_match_rate: float
    nondiscrimination_test_method: str
    prior_year_nhce_acp: float
    unpaid_leave_day_cap: int
    leave_merge_buffer_days: int
    total_deferral_match_funded_cents: int
    total_qslp_match_funded_cents: int
    forfeiture_balance_cents: int
    accepted_certification_count: int
    true_up_completed: bool
    reopened_count: int


class PlanAmendment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    plan_year_id: str
    document_ref: str
    effective_date: str
    status: str
    adopted_at: Optional[str]
    notice_sent_at: Optional[str]
    effective_at: Optional[str]
    notice_channel: Optional[str]
    rescinded_reason: Optional[str]


class Employee(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    external_id: str
    hire_date: str
    prior_year_compensation_cents: int
    vesting_service_months: int
    employment_status: str
    termination_date: Optional[str]
    rehire_date: Optional[str]
    hce_flag: bool
    ytd_eligible_compensation_cents: int
    ytd_deferral_cents: int
    ytd_deferral_match_cents: int
    ytd_qslp_match_cents: int
    remaining_qslp_space_cents: Optional[int]
    vested_pct: float
    unpaid_leave_days_ytd: int


class PayrollPeriod(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    plan_year_id: str
    period_number: int
    start_date: str
    end_date: str
    pay_date: str
    status: str
    reopen_count: int
    total_eligible_compensation_cents: int
    total_deferral_match_cents: int


class ContributionRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_id: str
    payroll_period_id: str
    eligible_compensation_cents: int
    elective_deferral_cents: int
    counted_compensation_cents: int
    deferral_match_cents: int
    qslp_space_tier1_cents: int
    qslp_space_tier2_cents: int


class LoanAccount(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_id: str
    servicer_name: str
    account_last4: str
    original_principal_cents: int
    status: str
    evidence_ref: Optional[str]


class LoanCertification(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_id: str
    plan_year_id: str
    supersedes_certification_id: Optional[str]
    certification_method: str
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    accepted_by_user_id: Optional[str]
    return_count: int
    certified_total_cents: int
    eligible_total_cents: int
    matched_total_cents: int
    unmatched_eligible_cents: int
    capped_by_statutory_room: bool
    audit_hold_reason: Optional[str]
    void_reason: Optional[str]


class MatchAllocation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_id: str
    plan_year_id: str
    certification_id: Optional[str]
    payroll_period_id: Optional[str]
    funding_batch_id: Optional[str]
    allocation_type: str
    amount_cents: int
    tier1_applied_cents: int
    tier2_applied_cents: int
    funding_status: str
    vesting_status: str
    vested_cents: int
    forfeited_cents: int


class FundingBatch(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    plan_year_id: str
    payroll_period_id: str
    status: str
    total_allocated_cents: int
    allocation_count: int
    forfeiture_offset_cents: int
    net_funding_cents: int
    transmitted_at: Optional[str]
    settled_at: Optional[str]
    rejection_code: Optional[str]
    retransmit_count: int


class NondiscriminationTest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    plan_year_id: str
    test_method: str
    include_qslp_match: bool
    status: str
    hce_acp: float
    nhce_acp: float
    limit_acp: float
    hce_count: int
    nhce_count: int
    computed_at: Optional[str]
    correction_method: Optional[str]
    total_correction_cents: int


# ---------------------------------------------------------------------------
# Append-only audit rows — id / created_at only (PRD §2.4)
# ---------------------------------------------------------------------------


class LeaveEvent(TypedDict):
    id: str
    created_at: str
    employee_id: str
    leave_type: str
    start_date: str
    end_date: str
    day_count: int


class CertificationLine(TypedDict):
    id: str
    created_at: str
    certification_id: str
    loan_account_id: str
    payment_date: str
    amount_cents: int
    covered_period_start: str
    covered_period_end: str


class ForfeitureRecord(TypedDict):
    id: str
    created_at: str
    match_allocation_id: str
    employee_id: str
    plan_year_id: str
    amount_cents: int
    reason_code: str


class CorrectionAdjustment(TypedDict):
    id: str
    created_at: str
    match_allocation_id: Optional[str]
    employee_id: str
    plan_year_id: str
    nondiscrimination_test_id: Optional[str]
    reason_code: str
    amount_cents: int
    created_by_user_id: str
    note: Optional[str]


# ---------------------------------------------------------------------------
# Computed reads that are not stored resources
# ---------------------------------------------------------------------------


class AuditPacket(TypedDict):
    employee_id: str
    plan_year_id: str
    certification_count: int
    accepted_certified_cents: int
    deferral_match_cents: int
    qslp_match_cents: int
    forfeited_cents: int
    correction_cents: int
    remaining_space_cents: int
