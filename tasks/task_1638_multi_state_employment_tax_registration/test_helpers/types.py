"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class UserRole(str, Enum):
    TAX_DIRECTOR = "TaxDirector"
    NEXUS_ANALYST = "NexusAnalyst"
    UI_SPECIALIST = "UISpecialist"
    PAYROLL_COMPLIANCE_LEAD = "PayrollComplianceLead"
    EMPLOYEE = "Employee"
    AUDITOR = "Auditor"


class CompliancePosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    DELINQUENT = "DELINQUENT"


class AgencyKind(str, Enum):
    STATE_WITHHOLDING = "STATE_WITHHOLDING"
    STATE_UI = "STATE_UI"
    LOCAL = "LOCAL"


class AgreementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class LocationType(str, Enum):
    COMPANY_OFFICE = "COMPANY_OFFICE"
    REMOTE_HOME = "REMOTE_HOME"
    CLIENT_SITE = "CLIENT_SITE"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class NexusCaseStatus(str, Enum):
    WATCH = "WATCH"
    THRESHOLD_MET = "THRESHOLD_MET"
    CONFIRMED = "CONFIRMED"
    EXEMPT = "EXEMPT"
    LAPSED = "LAPSED"


class ThresholdBasis(str, Enum):
    NONE = "NONE"
    DAYS = "DAYS"
    WAGES = "WAGES"
    BOTH = "BOTH"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class FilingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMIWEEKLY = "SEMIWEEKLY"


class DepositTier(str, Enum):
    STANDARD = "STANDARD"
    ACCELERATED = "ACCELERATED"
    NEXT_DAY = "NEXT_DAY"


class FrequencyBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    LOOKBACK = "LOOKBACK"


class ElectionType(str, Enum):
    RECIPROCITY_EXEMPTION = "RECIPROCITY_EXEMPTION"
    COURTESY_RESIDENT = "COURTESY_RESIDENT"
    COURTESY_WORK = "COURTESY_WORK"


class ElectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ResolutionSource(str, Enum):
    AUTO_GEOCODE = "AUTO_GEOCODE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class LocalAssignmentStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class UIRateStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONTESTED = "CONTESTED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class VCStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    REMITTED = "REMITTED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"


class LocationChangeStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EFFECTIVE = "EFFECTIVE"
    REVERSED = "REVERSED"


class ObligationKind(str, Enum):
    WITHHOLDING_RETURN = "WITHHOLDING_RETURN"
    WITHHOLDING_DEPOSIT = "WITHHOLDING_DEPOSIT"
    UI_RETURN = "UI_RETURN"
    UI_CONTRIBUTION = "UI_CONTRIBUTION"
    LOCAL_RETURN = "LOCAL_RETURN"


class ObligationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    LATE = "LATE"
    FILED = "FILED"
    CONFIRMED = "CONFIRMED"
    WAIVED = "WAIVED"


class NoticeType(str, Enum):
    PENALTY_ASSESSMENT = "PENALTY_ASSESSMENT"
    RATE_NOTICE = "RATE_NOTICE"
    MISSING_RETURN = "MISSING_RETURN"
    ACCOUNT_INQUIRY = "ACCOUNT_INQUIRY"
    AUDIT = "AUDIT"


class NoticeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    RESPONSE_IN_PROGRESS = "RESPONSE_IN_PROGRESS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class NoticeSeverity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AbatementType(str, Enum):
    FIRST_TIME = "FIRST_TIME"
    REASONABLE_CAUSE = "REASONABLE_CAUSE"
    STATUTORY = "STATUTORY"


class AbatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    home_state_code: str
    compliance_posture: str
    open_notice_count: int
    outstanding_penalty_cents: int
    registered_state_count: int
    created_at: str
    updated_at: str
    version: int


class TaxAgency(TypedDict, total=False):
    id: str
    agency_kind: str
    state_code: str
    locality_code: Optional[str]
    agency_name: str
    withholding_rate_bp: Optional[int]
    resident_rate_bp: Optional[int]
    nonresident_rate_bp: Optional[int]
    precedence_rank: int
    new_employer_rate_bp: Optional[int]
    solvency_surcharge_bp: int
    ui_wage_base_cents: Optional[int]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class ReciprocityAgreement(TypedDict, total=False):
    id: str
    state_a: str
    state_b: str
    effective_from: str
    effective_to: Optional[str]
    certificate_form_code: Optional[str]
    scope: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkLocation(TypedDict, total=False):
    id: str
    label: str
    address_line1: str
    city: str
    state_code: str
    postal_code: str
    location_type: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employee_ref: str
    full_name: str
    resident_state_code: str
    resident_locality_code: Optional[str]
    hire_date: str
    annual_wage_cents: int
    status: str
    current_work_location_id: str
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NexusCase(TypedDict, total=False):
    id: str
    state_code: str
    status: str
    employee_days_ytd: int
    employee_days_trailing_90d: int
    wages_ytd_cents: int
    threshold_basis: str
    established_date: Optional[str]
    exempt_reason: Optional[str]
    last_recomputed_at: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    agency_id: str
    registration_kind: str
    state_code: str
    account_number: Optional[str]
    status: str
    filing_frequency: str
    deposit_tier: str
    frequency_basis: str
    projected_annual_withholding_cents: int
    lookback_liability_cents: int
    rejection_reason: Optional[str]
    submitted_at: Optional[str]
    activated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WithholdingElection(TypedDict, total=False):
    id: str
    employee_id: str
    election_type: str
    work_state_code: str
    resident_state_code: str
    certificate_form_code: Optional[str]
    effective_from: str
    effective_to: Optional[str]
    status: str
    supersedes_election_id: Optional[str]
    submitted_by_user_id: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LocalAssignment(TypedDict, total=False):
    id: str
    employee_id: str
    work_location_id: str
    effective_from: str
    effective_to: Optional[str]
    resident_agency_id: Optional[str]
    work_agency_id: Optional[str]
    resolution_source: str
    precedence_trace: str
    status: str
    override_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UIRate(TypedDict, total=False):
    id: str
    registration_id: str
    rate_year: int
    experience_rated: bool
    assigned_rate_bp: int
    contributions_paid_3yr_cents: int
    benefits_charged_3yr_cents: int
    taxable_payroll_3yr_cents: int
    voluntary_contribution_applied_cents: int
    reserve_ratio_bp: Optional[int]
    final_rate_bp: int
    status: str
    contest_reason: Optional[str]
    received_date: str
    created_at: str
    updated_at: str
    version: int


class VoluntaryContribution(TypedDict, total=False):
    id: str
    ui_rate_id: str
    proposed_amount_cents: int
    decision_deadline: str
    projected_rate_without_vc_bp: int
    projected_rate_with_vc_bp: int
    projected_net_savings_cents: int
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    remitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LocationChange(TypedDict, total=False):
    id: str
    employee_id: str
    to_work_location_id: str
    from_location_snapshot: Dict[str, Any]
    effective_date: str
    reason: str
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    impact_summary: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FilingObligation(TypedDict, total=False):
    id: str
    registration_id: str
    obligation_kind: str
    period_start: str
    period_end: str
    due_date: str
    amount_due_cents: int
    amount_paid_cents: int
    status: str
    filed_at: Optional[str]
    filed_by_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    late_days: int
    created_at: str
    updated_at: str
    version: int


class AgencyNotice(TypedDict, total=False):
    id: str
    registration_id: Optional[str]
    filing_obligation_id: Optional[str]
    notice_type: str
    received_date: str
    response_due_date: str
    penalty_amount_cents: int
    abated_amount_cents: int
    status: str
    severity: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbatementRequest(TypedDict, total=False):
    id: str
    agency_notice_id: str
    abatement_type: str
    requested_amount_cents: int
    reason: str
    eligible_amount_cents: int
    prior_penalty_count_3yr: int
    status: str
    prepared_by_user_id: str
    reviewed_by_user_id: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    granted_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
