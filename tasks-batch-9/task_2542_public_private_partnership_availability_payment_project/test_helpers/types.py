"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AUTHORITY_OFFICER = "AuthorityOfficer"
    CONCESSIONAIRE = "Concessionaire"
    LENDER_AGENT = "LenderAgent"
    INDEPENDENT_CERTIFIER = "IndependentCertifier"


class ConcessionaireStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STEPPED_IN = "STEPPED_IN"
    WOUND_UP = "WOUND_UP"


class ConcessionStatus(str, Enum):
    DRAFTED = "DRAFTED"
    FINANCIAL_CLOSE = "FINANCIAL_CLOSE"
    CONSTRUCTION = "CONSTRUCTION"
    OPERATIONS = "OPERATIONS"
    STEP_IN = "STEP_IN"
    TERMINATED = "TERMINATED"


class HandbackStatus(str, Enum):
    NOT_SURVEYED = "NOT_SURVEYED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class DrawdownMilestoneStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"


class ReportingStatus(str, Enum):
    PENDING = "PENDING"
    SELF_REPORTED = "SELF_REPORTED"
    VERIFIED = "VERIFIED"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    ADJUSTED = "ADJUSTED"


class PerformanceReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DeductionType(str, Enum):
    UNAVAILABILITY = "UNAVAILABILITY"
    PERFORMANCE_FAILURE = "PERFORMANCE_FAILURE"
    SELF_REPORT_UNDERSTATEMENT = "SELF_REPORT_UNDERSTATEMENT"
    HANDBACK_SHORTFALL = "HANDBACK_SHORTFALL"


class DeductionEventStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class DeductionDisputeStatus(str, Enum):
    RAISED = "RAISED"
    REFERRED_BACK = "REFERRED_BACK"
    RESUBMITTED = "RESUBMITTED"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class ClaimType(str, Enum):
    RELIEF_EVENT = "RELIEF_EVENT"
    COMPENSATION_EVENT = "COMPENSATION_EVENT"
    CHANGE_IN_LAW = "CHANGE_IN_LAW"


class ReliefClaimStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    REJECTED = "REJECTED"


class ReserveTxnType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    WITHDRAWAL = "WITHDRAWAL"
    HANDBACK_TOPUP = "HANDBACK_TOPUP"
    REVERSAL = "REVERSAL"


class RefinancingEventStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONSENTED = "CONSENTED"
    REJECTED = "REJECTED"


class EnforcementActionType(str, Enum):
    STEP_IN = "STEP_IN"
    TERMINATION = "TERMINATION"


class EnforcementTriggerReason(str, Enum):
    PERSISTENT_BREACH = "PERSISTENT_BREACH"
    LENDER_DEFAULT_CURE = "LENDER_DEFAULT_CURE"
    AUTHORITY_VOLUNTARY = "AUTHORITY_VOLUNTARY"
    CONCESSIONAIRE_DEFAULT = "CONCESSIONAIRE_DEFAULT"
    AUTHORITY_DEFAULT = "AUTHORITY_DEFAULT"
    FORCE_MAJEURE = "FORCE_MAJEURE"


class EnforcementActionStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    STEP_IN_ACTIVE = "STEP_IN_ACTIVE"
    CURED = "CURED"
    LAPSED = "LAPSED"
    COMPENSATION_CALCULATED = "COMPENSATION_CALCULATED"
    SETTLED = "SETTLED"


# --- Entities carrying id + created_at + updated_at + version ----------------

class Concessionaire(TypedDict):
    id: str
    legal_name: str
    sponsor_equity_commitment_cents: int
    status: str
    concessions_count: int
    created_at: str
    updated_at: str
    version: int


class Concession(TypedDict):
    id: str
    project_name: str
    concessionaire_id: str
    status: str
    masp_cents: int
    indexation_pct: float
    deduction_cap_pct: float
    total_project_cost_cents: int
    senior_debt_committed_cents: int
    equity_committed_cents: int
    base_case_equity_irr_bps: int
    scheduled_service_commencement: str
    ld_daily_rate_cents: int
    ld_cap_cents: int
    lifecycle_reserve_target_cents: int
    financial_close_date: Optional[str]
    monthly_unitary_charge_cents: Optional[int]
    senior_debt_drawn_cents: int
    equity_drawn_cents: int
    cumulative_drawn_pct: float
    actual_service_commencement: Optional[str]
    ld_accrued_cents: int
    lifecycle_reserve_balance_cents: int
    availability_deduction_ytd_cents: int
    deduction_points_ytd: int
    persistent_breach_flag: bool
    handback_survey_date: Optional[str]
    handback_rectification_cost_cents: Optional[int]
    handback_required_reserve_cents: Optional[int]
    handback_shortfall_cents: Optional[int]
    handback_status: str
    created_at: str
    updated_at: str
    version: int


class DrawdownMilestone(TypedDict):
    id: str
    concession_id: str
    sequence_no: int
    milestone_name: str
    requested_amount_cents: int
    certified_cost_cents: Optional[int]
    status: str
    equity_portion_cents: Optional[int]
    debt_portion_cents: Optional[int]
    rejection_reason: Optional[str]
    approved_at: Optional[str]
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServicePeriod(TypedDict):
    id: str
    concession_id: str
    period_index: int
    period_start: str
    period_end: str
    days_in_period: int
    reporting_status: str
    payment_status: str
    gross_unitary_charge_cents: int
    deduction_cap_cents: int
    unavailable_minutes_verified: Optional[int]
    deduction_points_total: int
    total_deduction_cents: int
    relief_credit_cents: int
    net_payment_cents: int
    availability_ratio: Optional[float]
    verified_at: Optional[str]
    invoiced_at: Optional[str]
    paid_at: Optional[str]
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReport(TypedDict):
    id: str
    service_period_id: str
    unavailable_minutes: int
    category_a_failures: int
    category_b_failures: int
    reported_points: int
    status: str
    variance_pct: Optional[float]
    rejection_reason: Optional[str]
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class DeductionEvent(TypedDict):
    id: str
    service_period_id: str
    performance_report_id: Optional[str]
    sequence_no: int
    deduction_type: str
    points: int
    raw_amount_cents: int
    allowed_amount_cents: int
    pro_rata_amount_cents: int
    status: str
    issued_by_user_id: str
    issued_at: str
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeductionDispute(TypedDict):
    id: str
    deduction_event_id: str
    raised_by_user_id: str
    grounds: str
    round_no: int
    status: str
    referred_back_reason: Optional[str]
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReliefClaim(TypedDict):
    id: str
    concession_id: str
    claim_type: str
    event_start: str
    event_end: str
    notified_at: str
    claimed_relief_days: int
    claimed_cost_cents: int
    granted_relief_days: int
    granted_cost_cents: int
    status: str
    determined_at: Optional[str]
    determination_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefinancingEvent(TypedDict):
    id: str
    concession_id: str
    refinancing_date: str
    new_senior_debt_cents: int
    outstanding_senior_debt_cents: int
    refinancing_cost_cents: int
    gross_gain_cents: int
    tier_pct_applied: float
    authority_share_cents: int
    concessionaire_share_cents: int
    reserve_sweep_cents: int
    proposed_by_user_id: str
    status: str
    consented_by_user_id: Optional[str]
    consented_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    concession_id: str
    action_type: str
    trigger_reason: str
    initiated_by_role: str
    effective_date: str
    cure_deadline: Optional[str]
    status: str
    outstanding_senior_debt_cents: Optional[int]
    market_value_estimate_cents: Optional[int]
    rectification_cost_cents: Optional[int]
    authority_reprocurement_cost_cents: Optional[int]
    termination_date: Optional[str]
    elapsed_operational_months: Optional[int]
    accrued_equity_return_cents: Optional[int]
    unpaid_invoiced_cents: Optional[int]
    deduction_offset_cents: Optional[int]
    compensation_cents: Optional[int]
    calculated_by_user_id: Optional[str]
    cure_note: Optional[str]
    cured_at: Optional[str]
    settled_at: Optional[str]
    settlement_reference: Optional[str]
    escalated_to_action_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity: carries only id + created_at ------------------------

class LifecycleReserveTransaction(TypedDict):
    id: str
    concession_id: str
    sequence_no: int
    txn_type: str
    amount_cents: int
    signed_amount_cents: int
    reason: str
    reverses_txn_id: Optional[str]
    resulting_balance_cents: int
    created_by_role: str
    created_at: str
