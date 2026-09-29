"""Domain types for the Certified Payroll & Prevailing Wage Compliance API."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PORTAL_ADMIN = "PortalAdmin"
    PAYROLL_PREPARER = "PayrollPreparer"
    CERTIFYING_OFFICIAL = "CertifyingOfficial"
    AGENCY_COMPLIANCE_OFFICER = "AgencyComplianceOfficer"
    LABOR_STANDARDS_AUDITOR = "LaborStandardsAuditor"


class SubmissionFormat(str, Enum):
    WH347_PDF = "WH347_PDF"
    XML_LCP = "XML_LCP"
    CSV_FLAT = "CSV_FLAT"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ZoneCode(str, Enum):
    BASE = "BASE"
    ZONE1 = "ZONE1"
    ZONE2 = "ZONE2"


class DebarmentStatus(str, Enum):
    CLEAR = "CLEAR"
    PROPOSED = "PROPOSED"
    DEBARRED = "DEBARRED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"


class ProgramRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PROVISIONAL = "PROVISIONAL"
    LAPSED = "LAPSED"


class StaffCapability(str, Enum):
    PREPARER = "PREPARER"
    CERTIFIER = "CERTIFIER"
    BOTH = "BOTH"


class PlanType(str, Enum):
    BONA_FIDE_TRUST = "BONA_FIDE_TRUST"
    UNFUNDED = "UNFUNDED"
    CASH_IN_LIEU = "CASH_IN_LIEU"


class PlanApprovalStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FundingSource(str, Enum):
    FEDERAL_DAVIS_BACON = "FEDERAL_DAVIS_BACON"
    STATE_ONLY = "STATE_ONLY"
    DUAL = "DUAL"


class ProjectStatus(str, Enum):
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    SUBSTANTIALLY_COMPLETE = "SUBSTANTIALLY_COMPLETE"
    CLOSED = "CLOSED"


class ProjectPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AssignmentStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class ComplianceStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    RESTITUTION_PENDING = "RESTITUTION_PENDING"
    REMEDIED = "REMEDIED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED_MATCHED = "CONDUCTED_MATCHED"
    CONDUCTED_DISCREPANT = "CONDUCTED_DISCREPANT"
    CANCELLED = "CANCELLED"


class FindingType(str, Enum):
    UNDERPAYMENT = "UNDERPAYMENT"
    MISCLASSIFICATION = "MISCLASSIFICATION"
    APPRENTICE_RATIO = "APPRENTICE_RATIO"
    FRINGE_CREDIT = "FRINGE_CREDIT"
    MISSING_PAYROLL = "MISSING_PAYROLL"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    RESPONSE_REJECTED = "RESPONSE_REJECTED"
    RESPONSE_ACCEPTED = "RESPONSE_ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    DISBURSED = "DISBURSED"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


# --- Entity shapes -----------------------------------------------------------
# Resources carrying updated_at and version: wage determination, contractor,
# apprenticeship program, fringe benefit plan, project, contract assignment,
# worker, payroll submission, on-site interview, finding, restitution payment.
# Resources carrying only id and created_at: reporting portal, wage rate row,
# contractor staff row, payroll line.


class ReportingPortal(TypedDict):
    id: str
    portal_code: str
    submission_format: str
    cutoff_offset_days: int
    grace_hours: int
    requires_notarized_statement: bool
    created_at: str


class WageDetermination(TypedDict):
    id: str
    decision_number: str
    modification_number: int
    locality_code: str
    effective_date: str
    expiry_date: Optional[str]
    status: str
    superseded_by_id: Optional[str]
    rate_count: int
    created_at: str
    updated_at: str
    version: int


class WageRate(TypedDict):
    id: str
    wage_determination_id: str
    classification_code: str
    trade_code: str
    zone_code: str
    base_hourly_rate_cents: int
    fringe_hourly_rate_cents: int
    zone_adjustment_cents: int
    apprentice_scale_pct: List[int]
    created_at: str


class Contractor(TypedDict):
    id: str
    legal_name: str
    parent_contractor_id: Optional[str]
    dir_registration_number: str
    registration_status: str
    debarment_status: str
    debarment_risk_score: int
    last_finding_at: Optional[str]
    open_critical_finding_count: int
    outstanding_restitution_cents: int
    created_at: str
    updated_at: str
    version: int


class ContractorStaff(TypedDict):
    id: str
    contractor_id: str
    full_name: str
    capability: str
    notary_reference_number: Optional[str]
    created_at: str


class ApprenticeProgram(TypedDict):
    id: str
    registration_number: str
    sponsor_name: str
    trade_code: str
    registration_status: str
    allowed_apprentice_hours_per_100_journey: int
    period_count: int
    created_at: str
    updated_at: str
    version: int


class FringeBenefitPlan(TypedDict):
    id: str
    contractor_id: str
    plan_name: str
    plan_type: str
    annual_contribution_cents: int
    annual_total_hours: float
    annual_public_works_hours: float
    approval_status: str
    annualized_credit_cents: int
    claimed_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    project_name: str
    awarding_agency: str
    locality_code: str
    zone_code: str
    wage_determination_id: str
    reporting_portal_id: str
    funding_source: str
    contract_award_date: str
    status: str
    posture: str
    open_finding_count: int
    open_critical_finding_count: int
    outstanding_restitution_cents: int
    suspended_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ContractAssignment(TypedDict):
    id: str
    project_id: str
    contractor_id: str
    upper_tier_assignment_id: Optional[str]
    tier: int
    subcontract_amount_cents: int
    status: str
    cumulative_certified_hours: float
    cumulative_restitution_cents: int
    open_finding_count: int
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    employer_contractor_id: str
    worker_number: str
    full_name: str
    default_classification_code: str
    apprentice_program_id: Optional[str]
    apprentice_period: Optional[int]
    interview_count: int
    created_at: str
    updated_at: str
    version: int


class PayrollSubmission(TypedDict):
    id: str
    contract_assignment_id: str
    week_ending_date: str
    prepared_by_staff_id: str
    certified_by_staff_id: Optional[str]
    superseded_submission_id: Optional[str]
    no_work_performed: bool
    workflow_status: str
    compliance_status: str
    statement_signed_at: Optional[str]
    notary_reference_number: Optional[str]
    submitted_at: Optional[str]
    filing_due_at: Optional[str]
    is_late: bool
    accepted_by_user_id: Optional[str]
    total_hours_reported: float
    straight_time_underpayment_cents: int
    make_whole_underpayment_cents: int
    excess_apprentice_hours: float
    created_at: str
    updated_at: str
    version: int


class PayrollLine(TypedDict):
    id: str
    payroll_submission_id: str
    worker_id: str
    fringe_plan_id: Optional[str]
    classification_code: str
    straight_hours: float
    overtime_hours: float
    base_rate_paid_cents: int
    overtime_rate_paid_cents: int
    fringe_cash_paid_cents: int
    reported_as_apprentice: bool
    required_base_cents: int
    required_fringe_cents: int
    creditable_fringe_cents: int
    reclassified_journey_hours: float
    line_underpayment_cents: int
    created_at: str


class OnSiteInterview(TypedDict):
    id: str
    project_id: str
    contract_assignment_id: str
    worker_id: str
    window_start: str
    window_end: str
    observed_classification_code: Optional[str]
    observed_hourly_rate_cents: Optional[int]
    status: str
    compared_submission_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict):
    id: str
    project_id: str
    payroll_submission_id: str
    worker_id: Optional[str]
    source_interview_id: Optional[str]
    finding_type: str
    severity: str
    restitution_required_cents: int
    restitution_outstanding_cents: int
    status: str
    response_round: int
    raised_by_user_id: str
    response_due_at: str
    response_narrative: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestitutionPayment(TypedDict):
    id: str
    finding_id: str
    worker_id: str
    amount_cents: int
    status: str
    disbursed_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
