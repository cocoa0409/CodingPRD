"""Domain types: entity shapes, status enums and the role enum for this API."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FUND_ADMINISTRATOR = "FundAdministrator"
    CONTRIBUTING_EMPLOYER = "ContributingEmployer"
    TRUSTEE = "Trustee"
    PAYROLL_AUDITOR = "PayrollAuditor"
    ACTUARY = "Actuary"


class FundRole(str, Enum):
    HOME = "HOME"
    SISTER = "SISTER"


class GovernancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ReciprocityAgreementStatus(str, Enum):
    NONE = "NONE"
    EXECUTED = "EXECUTED"


class AccrualMethod(str, Enum):
    HOURS_BASED = "HOURS_BASED"
    ELAPSED_TIME = "ELAPSED_TIME"


class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BROKEN_SERVICE = "BROKEN_SERVICE"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class FilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID_IN_FULL = "PAID_IN_FULL"
    DELINQUENT = "DELINQUENT"


class ReportOrigin(str, Enum):
    EMPLOYER = "EMPLOYER"
    AUDIT = "AUDIT"


class WorkClassification(str, Enum):
    JOURNEYMAN = "JOURNEYMAN"
    APPRENTICE = "APPRENTICE"
    FOREMAN = "FOREMAN"


class DelinquencyBasis(str, Enum):
    STATUTORY = "STATUTORY"
    PLAN_SCHEDULE = "PLAN_SCHEDULE"


class DelinquencyAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class PayrollAuditStatus(str, Enum):
    IN_FIELDWORK = "IN_FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    EMPLOYER_ACCEPTED = "EMPLOYER_ACCEPTED"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class CoverageMonthStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class CoverageMonthSource(str, Enum):
    CURRENT_HOURS = "CURRENT_HOURS"
    BANK_DRAW = "BANK_DRAW"
    RECIPROCAL = "RECIPROCAL"


class AccrualStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class WithdrawalMethod(str, Enum):
    PRESUMPTIVE = "PRESUMPTIVE"
    ROLLING_FIVE = "ROLLING_FIVE"


class WithdrawalStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    DEMANDED = "DEMANDED"
    REVIEW_REQUESTED = "REVIEW_REQUESTED"
    PAYMENT_ACTIVE = "PAYMENT_ACTIVE"
    ACCELERATED = "ACCELERATED"
    SATISFIED = "SATISFIED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    MISSED = "MISSED"
    DEFAULTED = "DEFAULTED"


class AppointingParty(str, Enum):
    UNION = "UNION"
    EMPLOYER = "EMPLOYER"


class SeatStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"


class MotionSubjectType(str, Enum):
    LD_WAIVER = "LD_WAIVER"
    AUDIT_SETTLEMENT = "AUDIT_SETTLEMENT"
    RECIPROCITY_AGREEMENT = "RECIPROCITY_AGREEMENT"


class BlocPosition(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    TIED = "TIED"


class VotePosition(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


class MotionStatus(str, Enum):
    OPEN = "OPEN"
    CARRIED = "CARRIED"
    FAILED = "FAILED"
    DEADLOCKED = "DEADLOCKED"
    ARBITRATION_CARRIED = "ARBITRATION_CARRIED"
    ARBITRATION_FAILED = "ARBITRATION_FAILED"


class TransferType(str, Enum):
    MONEY_FOLLOWS_MAN = "MONEY_FOLLOWS_MAN"
    PRO_RATA = "PRO_RATA"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity shapes.  Resources that carry updated_at and version list them; the
# two immutable ledger rows (contribution lines, motion votes) carry only
# id and created_at.
# --------------------------------------------------------------------------


class Fund(TypedDict):
    id: str
    name: str
    ein: str
    fund_role: str
    plan_year_start_month: int
    interest_rate_annual_bps: int
    ld_rate_bps: int
    ld_floor_cents: int
    grace_days: int
    hours_per_coverage_month: int
    bank_cap_hours: float
    max_advance_coverage_months: int
    eligibility_lag_months: int
    accrual_method: str
    total_uvb_cents: int
    pool_prior_year_contributions_cents: List[int]
    allocated_uvb_cents: int
    unallocated_uvb_cents: int
    reciprocity_agreement_status: str
    active_union_trustees: int
    active_employer_trustees: int
    governance_posture: str
    suspended_employer_count: int
    reciprocal_receipts_cents: int
    collections_run_index: int
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    fund_id: str
    legal_name: str
    ein: str
    contribution_rate_millicents_per_hour: int
    controlled_group_parent_employer_id: Optional[str]
    prior_year_contributions_cents: List[int]
    prior_year_base_units: List[int]
    status: str
    delinquency_strikes: int
    cumulative_delinquent_cents: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    fund_id: str
    full_name: str
    ssn_last4: str
    credited_hours_total: float
    reciprocal_hours_total: float
    hour_bank_hours: float
    forfeited_hours_total: float
    coverage_through_month: Optional[str]
    eligibility_status: str
    vesting_service_years: int
    total_pension_credits: float
    vested: bool
    consecutive_break_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContributionReport(TypedDict):
    id: str
    employer_id: str
    work_period: str
    amends_report_id: Optional[str]
    origin: str
    due_date: str
    total_hours_reported: float
    total_contributions_due_cents: int
    amount_remitted_cents: int
    filing_status: str
    payment_status: str
    posted_at: Optional[str]
    paid_in_full_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContributionLine(TypedDict):
    """Immutable ledger row: id and created_at only."""

    id: str
    report_id: str
    participant_id: str
    hours: float
    gross_wages_cents: int
    work_classification: str
    contribution_cents: int
    created_at: str


class DelinquencyAssessment(TypedDict):
    id: str
    report_id: str
    basis: str
    assessed_on: str
    days_late: int
    principal_cents: int
    interest_cents: int
    liquidated_damages_cents: int
    total_cents: int
    status: str
    settlement_amount_cents: Optional[int]
    waived_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PayrollAudit(TypedDict):
    id: str
    employer_id: str
    auditor_user_id: str
    period_start_month: str
    period_end_month: str
    findings: list
    round_count: int
    unreported_hours_found: float
    underpayment_principal_cents: int
    resulting_report_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageMonth(TypedDict):
    id: str
    participant_id: str
    coverage_month: str
    granting_report_id: Optional[str]
    source: str
    hours_applied: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PensionAccrual(TypedDict):
    id: str
    participant_id: str
    plan_year: int
    hours_credited: float
    reciprocal_hours_credited: float
    pension_credit: float
    vesting_year_earned: bool
    break_in_service: bool
    accrual_status: str
    created_at: str
    updated_at: str
    version: int


class WithdrawalAssessment(TypedDict):
    id: str
    employer_id: str
    withdrawal_date: str
    method: str
    employer_share_fraction: float
    raw_allocation_cents: int
    de_minimis_reduction_cents: int
    net_liability_cents: int
    annual_payment_cents: int
    schedule_years: int
    twenty_year_cap_applied: bool
    capped_liability_cents: int
    accelerated_balance_cents: Optional[int]
    certified_by_user_id: Optional[str]
    demanded_on: Optional[str]
    review_grounds: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentInstallment(TypedDict):
    id: str
    assessment_id: str
    installment_number: int
    due_date: str
    amount_cents: int
    status: str
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trustee(TypedDict):
    id: str
    fund_id: str
    full_name: str
    appointing_party: str
    term_expires_on: str
    seat_status: str
    created_at: str
    updated_at: str
    version: int


class BoardMotion(TypedDict):
    id: str
    fund_id: str
    moved_by_trustee_id: str
    subject_type: str
    subject_ref_id: str
    union_bloc_position: Optional[str]
    employer_bloc_position: Optional[str]
    tallied_on: Optional[str]
    arbitration_award: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MotionVote(TypedDict):
    """Immutable ledger row: id and created_at only."""

    id: str
    motion_id: str
    trustee_id: str
    position: str
    created_at: str


class ReciprocityTransfer(TypedDict):
    id: str
    participant_id: str
    sister_fund_id: str
    transfer_type: str
    work_period: str
    hours: float
    amount_cents: int
    applied_coverage_months: int
    status: str
    created_at: str
    updated_at: str
    version: int
