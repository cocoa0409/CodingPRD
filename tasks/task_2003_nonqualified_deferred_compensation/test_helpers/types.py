"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class DocumentPosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    FAILURE_OPEN = "FAILURE_OPEN"
    LAPSED_FAILURE = "LAPSED_FAILURE"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SEPARATION_REVIEW = "SEPARATION_REVIEW"
    SEPARATED = "SEPARATED"
    DISABLED = "DISABLED"
    DECEASED = "DECEASED"


class ElectionWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ElectionType(str, Enum):
    GENERAL = "GENERAL"
    NEWLY_ELIGIBLE = "NEWLY_ELIGIBLE"
    PERFORMANCE = "PERFORMANCE"


class CreditingMode(str, Enum):
    FIXED_RATE = "FIXED_RATE"
    INDEX_LINKED = "INDEX_LINKED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FLAGGED_FOR_INCLUSION = "FLAGGED_FOR_INCLUSION"
    CLOSED = "CLOSED"


class EntryType(str, Enum):
    DEFERRAL_CREDIT = "DEFERRAL_CREDIT"
    CREDITING_GAIN = "CREDITING_GAIN"
    CREDITING_REVERSAL = "CREDITING_REVERSAL"
    DISTRIBUTION_DEBIT = "DISTRIBUTION_DEBIT"


class EntryStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"


class CreditingRunStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class TrustPosture(str, Enum):
    UNFUNDED = "UNFUNDED"
    UNDERFUNDED = "UNDERFUNDED"
    FUNDED = "FUNDED"


class FundingEventType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    VALUATION_ADJUSTMENT = "VALUATION_ADJUSTMENT"
    CIC_MANDATORY_FUNDING = "CIC_MANDATORY_FUNDING"
    TRUST_DISTRIBUTION = "TRUST_DISTRIBUTION"


class SeparationCaseStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    DETERMINED_SEPARATED = "DETERMINED_SEPARATED"
    DETERMINED_NOT_SEPARATED = "DETERMINED_NOT_SEPARATED"
    REOPENED = "REOPENED"


class TriggerReason(str, Enum):
    RESIGNATION = "RESIGNATION"
    TERMINATION = "TERMINATION"
    RETIREMENT = "RETIREMENT"
    SERVICE_REDUCTION = "SERVICE_REDUCTION"


class DeterminationOutcome(str, Enum):
    CONFIRMED_SEPARATION = "CONFIRMED_SEPARATION"
    REBUTTED_CONTINUED_SERVICE = "REBUTTED_CONTINUED_SERVICE"


class SpecifiedListStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class MemberBasis(str, Enum):
    OFFICER = "OFFICER"
    FIVE_PERCENT_OWNER = "FIVE_PERCENT_OWNER"
    COMPENSATION_THRESHOLD = "COMPENSATION_THRESHOLD"


class DistributionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    EVENT_VERIFIED = "EVENT_VERIFIED"
    SCHEDULED = "SCHEDULED"
    PAYABLE = "PAYABLE"
    ON_HOLD = "ON_HOLD"
    PAID = "PAID"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class DistributionEventType(str, Enum):
    SEPARATION = "SEPARATION"
    DEATH = "DEATH"
    DISABILITY = "DISABILITY"
    FIXED_TIME = "FIXED_TIME"
    UNFORESEEABLE_EMERGENCY = "UNFORESEEABLE_EMERGENCY"
    CHANGE_IN_CONTROL = "CHANGE_IN_CONTROL"


class CicEventType(str, Enum):
    OWNERSHIP_CHANGE = "OWNERSHIP_CHANGE"
    EFFECTIVE_CONTROL_CHANGE = "EFFECTIVE_CONTROL_CHANGE"
    ASSET_CHANGE = "ASSET_CHANGE"


class CicStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class FailureType(str, Enum):
    EARLY_PAYMENT = "EARLY_PAYMENT"
    LATE_PAYMENT = "LATE_PAYMENT"
    EXCESS_DEFERRAL = "EXCESS_DEFERRAL"
    IMPROPER_ACCELERATION = "IMPROPER_ACCELERATION"


class FailureStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    QUANTIFIED = "QUANTIFIED"
    INCLUSION_ASSESSED = "INCLUSION_ASSESSED"
    CORRECTED = "CORRECTED"


class FindingStatus(str, Enum):
    REPORTED = "REPORTED"
    CORRECTION_FILED = "CORRECTION_FILED"
    CORRECTED = "CORRECTED"
    LAPSED = "LAPSED"


class UserRole(str, Enum):
    PLAN_SPONSOR = "PlanSponsor"
    BENEFITS_ADMIN = "BenefitsAdministrator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRUST_OFFICER = "TrustOfficer"
    PARTICIPANT = "Participant"
    PLATFORM_ADMIN = "PlatformAdmin"


class Plan(TypedDict, total=False):
    id: str
    name: str
    effective_date: str
    distribution_events_allowed: List[str]
    six_month_delay_enabled: bool
    rabbi_trust_required: bool
    accelerate_on_cic: bool
    separation_fraction_test: str
    vesting_cliff_years: int
    officer_comp_threshold_cents: int
    processing_lag_days: int
    status: str
    document_posture: str
    termination_effective_date: Optional[str]
    open_findings_count: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    plan_id: str
    employee_ref: str
    hire_date: str
    initial_eligibility_date: str
    annual_compensation_cents: int
    status: str
    is_specified_employee: bool
    separation_date: Optional[str]
    inclusion_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class ElectionWindow(TypedDict, total=False):
    id: str
    plan_id: str
    plan_year: int
    general_open_date: str
    general_close_date: str
    performance_period_start: Optional[str]
    performance_period_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeferralElection(TypedDict, total=False):
    id: str
    participant_id: str
    election_window_id: str
    notional_fund_id: str
    plan_id: str
    election_type: str
    deferral_percent_bp: int
    status: str
    elected_cap_cents: Optional[int]
    posted_cents: int
    submitted_at: Optional[str]
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NotionalFund(TypedDict, total=False):
    id: str
    plan_id: str
    ticker: str
    crediting_mode: str
    annual_rate_bp: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    participant_id: str
    plan_id: str
    status: str
    settled_balance_cents: int
    provisional_balance_cents: int
    vested_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AccountLedgerEntry(TypedDict, total=False):
    # Append-only: id + created_at only, NO updated_at / NO version (PRD §2.4)
    id: str
    account_id: str
    entry_type: str
    amount_cents: int
    fund_id: Optional[str]
    crediting_run_id: Optional[str]
    election_id: Optional[str]
    distribution_request_id: Optional[str]
    entry_status: str
    entry_date: str
    created_at: str


class CreditingRun(TypedDict, total=False):
    id: str
    plan_id: str
    period_start: str
    period_end: str
    index_rates: Optional[List[Dict[str, Any]]]
    status: str
    days_in_period: int
    total_gain_cents: int
    created_at: str
    updated_at: str
    version: int


class RabbiTrust(TypedDict, total=False):
    id: str
    plan_id: str
    funding_target_bp: int
    assets_cents: int
    cic_funding_required: bool
    required_funding_cents: int
    posture: str
    funding_events: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class SeparationCase(TypedDict, total=False):
    id: str
    participant_id: str
    alleged_separation_date: str
    trigger_reason: str
    opened_by_user_id: str
    service_records: List[Dict[str, Any]]
    computed_avg_fraction_bp: Optional[int]
    determination_threshold_bp: Optional[int]
    status: str
    determined_by_user_id: Optional[str]
    determined_at: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class SpecifiedEmployeeList(TypedDict, total=False):
    id: str
    plan_id: str
    identification_date: str
    effective_date: str
    status: str
    members: List[Dict[str, Any]]
    officer_cap_count: int
    created_at: str
    updated_at: str
    version: int


class DistributionRequest(TypedDict, total=False):
    id: str
    account_id: str
    participant_id: str
    separation_case_id: Optional[str]
    change_in_control_event_id: Optional[str]
    event_type: str
    requested_amount_cents: Optional[int]
    fixed_date: Optional[str]
    emergency_need_cents: Optional[int]
    locked_amount_cents: Optional[int]
    scheduled_payment_date: Optional[str]
    status: str
    denial_reason: Optional[str]
    verified_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeInControlEvent(TypedDict, total=False):
    id: str
    plan_id: str
    event_type: str
    effective_date: str
    stake_change_bp: int
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperationalFailureCase(TypedDict, total=False):
    id: str
    account_id: str
    distribution_request_id: Optional[str]
    participant_id: str
    failure_type: str
    failure_date: str
    amount_cents: int
    reported_by_user_id: str
    correction_credit_cents: Optional[int]
    includible_base_cents: Optional[int]
    premium_interest_cents: Optional[int]
    additional_tax_cents: Optional[int]
    total_inclusion_cents: Optional[int]
    correction_deadline: str
    status: str
    assessed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentFinding(TypedDict, total=False):
    id: str
    plan_id: str
    description: str
    failure_year: int
    correction_deadline: str
    correction_text: Optional[str]
    status: str
    filed_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
