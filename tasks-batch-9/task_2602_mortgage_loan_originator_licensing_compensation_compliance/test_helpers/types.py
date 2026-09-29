"""Domain types: entity TypedDicts, status enums and the role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LICENSING_ANALYST = "LicensingAnalyst"
    COMPENSATION_DESIGNER = "CompensationDesigner"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ORIGINATOR = "Originator"
    LOAN_OPERATIONS = "LoanOperations"
    EXAMINATION_COORDINATOR = "ExaminationCoordinator"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = [r.value for r in UserRole]


class EmploymentStatus(str, Enum):
    EMPLOYED = "EMPLOYED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MonitoringStatus(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"
    SURRENDERED = "SURRENDERED"
    REVOKED = "REVOKED"


class SponsorshipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELINQUISHED = "RELINQUISHED"
    SUPERSEDED = "SUPERSEDED"


class CeCategory(str, Enum):
    FEDERAL_LAW = "FEDERAL_LAW"
    ETHICS = "ETHICS"
    NONTRADITIONAL = "NONTRADITIONAL"
    STATE_SPECIFIC = "STATE_SPECIFIC"
    ELECTIVE = "ELECTIVE"


class ProviderStatus(str, Enum):
    APPROVED = "APPROVED"
    RESCINDED = "RESCINDED"


class CreditStatus(str, Enum):
    APPLIED = "APPLIED"
    EXCLUDED_SUCCESSIVE_YEAR = "EXCLUDED_SUCCESSIVE_YEAR"
    VOIDED = "VOIDED"


class VoidReason(str, Enum):
    ANALYST_VOID = "ANALYST_VOID"
    PROVIDER_RESCINDED = "PROVIDER_RESCINDED"


class AttributionVariant(str, Enum):
    MAKEUP_ATTRIBUTION = "MAKEUP_ATTRIBUTION"
    CALENDAR_YEAR_ATTRIBUTION = "CALENDAR_YEAR_ATTRIBUTION"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class Permissibility(str, Enum):
    PERMISSIBLE = "PERMISSIBLE"
    PROHIBITED = "PROHIBITED"


class VariableType(str, Enum):
    LOAN_VOLUME_UNITS = "LOAN_VOLUME_UNITS"
    LOAN_VOLUME_DOLLARS = "LOAN_VOLUME_DOLLARS"
    PERCENTAGE_OF_LOAN_AMOUNT = "PERCENTAGE_OF_LOAN_AMOUNT"
    HOURS_WORKED = "HOURS_WORKED"
    FILE_QUALITY_SCORE = "FILE_QUALITY_SCORE"
    EXISTING_BORROWER_FLAG = "EXISTING_BORROWER_FLAG"
    INTEREST_RATE = "INTEREST_RATE"
    APR = "APR"
    LOAN_TERM_MONTHS = "LOAN_TERM_MONTHS"
    LTV_RATIO = "LTV_RATIO"
    CREDIT_SCORE = "CREDIT_SCORE"
    PRODUCT_TYPE = "PRODUCT_TYPE"
    PREPAYMENT_PENALTY_FLAG = "PREPAYMENT_PENALTY_FLAG"
    LOAN_PROFITABILITY = "LOAN_PROFITABILITY"


class ProductType(str, Enum):
    FIXED_30 = "FIXED_30"
    FIXED_15 = "FIXED_15"
    ARM_5_1 = "ARM_5_1"
    FHA_30 = "FHA_30"
    VA_30 = "VA_30"


class LoanStatus(str, Enum):
    TAKEN = "TAKEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"
    PAID_OFF = "PAID_OFF"
    WITHDRAWN = "WITHDRAWN"


class CompensationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    ACCRUED = "ACCRUED"
    RECONCILED = "RECONCILED"
    CLAWED_BACK = "CLAWED_BACK"


class AuthorityFlag(str, Enum):
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"
    UNAUTHORIZED = "UNAUTHORIZED"


class ExceptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ReasonCode(str, Enum):
    COMPETITIVE_MATCH = "COMPETITIVE_MATCH"
    SERVICE_ISSUE = "SERVICE_ISSUE"
    PRICING_ERROR = "PRICING_ERROR"
    UNDERWRITING_DELAY = "UNDERWRITING_DELAY"
    RELATIONSHIP_PRICING = "RELATIONSHIP_PRICING"


class RecordVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class RecordStatus(str, Enum):
    ACCRUED = "ACCRUED"
    RECONCILED = "RECONCILED"
    CLAWED_BACK = "CLAWED_BACK"


class AdvertisementMedium(str, Enum):
    WEB = "WEB"
    PRINT = "PRINT"
    SOCIAL = "SOCIAL"
    DIRECT_MAIL = "DIRECT_MAIL"
    RADIO = "RADIO"


class AdvertisementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class InquiryStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class EscalationReason(str, Enum):
    ROUND_LIMIT_REACHED = "ROUND_LIMIT_REACHED"
    DEADLINE_MISSED = "DEADLINE_MISSED"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    REMEDIATED = "REMEDIATED"


class OpenedBy(str, Enum):
    CASCADE = "CASCADE"
    MANUAL = "MANUAL"


class TriggerReason(str, Enum):
    AUTHORITY_LAPSE = "AUTHORITY_LAPSE"
    STATE_NOT_AUTHORIZED = "STATE_NOT_AUTHORIZED"
    SPONSORSHIP_GAP = "SPONSORSHIP_GAP"
    MANUAL_REFERRAL = "MANUAL_REFERRAL"


class AuditEventType(str, Enum):
    LICENSE_STATUS_CHANGED = "LICENSE_STATUS_CHANGED"
    SPONSORSHIP_CHANGED = "SPONSORSHIP_CHANGED"
    CE_CREDIT_VOIDED = "CE_CREDIT_VOIDED"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_REJECTED = "PLAN_REJECTED"
    PROHIBITED_VARIABLE_BLOCKED = "PROHIBITED_VARIABLE_BLOCKED"
    APPLICATION_TAKEN = "APPLICATION_TAKEN"
    EXCEPTION_DECIDED = "EXCEPTION_DECIDED"
    COMP_ACCRUED = "COMP_ACCRUED"
    COMP_RECONCILED = "COMP_RECONCILED"
    COMP_CLAWED_BACK = "COMP_CLAWED_BACK"
    AD_DECIDED = "AD_DECIDED"
    INVESTIGATION_OPENED = "INVESTIGATION_OPENED"
    INVESTIGATION_FINDING = "INVESTIGATION_FINDING"
    MONITORING_ESCALATED = "MONITORING_ESCALATED"


class AuditSubjectType(str, Enum):
    ORIGINATOR = "Originator"
    LICENSE_REGISTRATION = "LicenseRegistration"
    SPONSORSHIP_TRANSFER = "SponsorshipTransfer"
    CE_CREDIT_RECORD = "CeCreditRecord"
    COMPENSATION_PLAN = "CompensationPlan"
    LOAN_APPLICATION = "LoanApplication"
    PRICING_EXCEPTION = "PricingException"
    COMPENSATION_RECORD = "CompensationRecord"
    ADVERTISEMENT = "Advertisement"
    EXAMINATION_INQUIRY = "ExaminationInquiry"
    UNLICENSED_ACTIVITY_INVESTIGATION = "UnlicensedActivityInvestigation"


# ---------------------------------------------------------------------------
# Entity shapes. Every entity below carries id / created_at / updated_at /
# version, except AuditEvent, which is append-only and carries only id and
# created_at (PRD 2.5).
# ---------------------------------------------------------------------------


class Originator(TypedDict):
    id: str
    nmls_unique_id: str
    legal_name: str
    hire_date: str
    employment_status: str
    compensation_plan_id: Optional[str]
    monitoring_status: str
    exposure_score: int
    lifetime_accrued_cents: int
    lifetime_clawed_back_cents: int
    net_compensation_cents: int
    authorized_state_codes: List[str]
    open_investigation_count: int
    created_at: str
    updated_at: str
    version: int


class LicenseRegistration(TypedDict):
    id: str
    originator_id: str
    state_code: str
    license_number: str
    issue_date: str
    expiration_date: str
    renewal_window_opens_at: str
    status: str
    authority_effective_at: Optional[str]
    required_ce_hours: int
    ce_hours_applied: int
    ce_reporting_year: int
    ce_satisfied: bool
    active_sponsoring_institution_code: Optional[str]
    active_sponsorship_effective_at: Optional[str]
    reinstatement_count: int
    created_at: str
    updated_at: str
    version: int


class SponsorshipTransfer(TypedDict):
    id: str
    license_registration_id: str
    sponsoring_institution_code: str
    effective_at: str
    relinquished_at: Optional[str]
    status: str
    superseded_by_created_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CeCourse(TypedDict):
    id: str
    course_code: str
    credit_hours: int
    category: str
    approved_state_codes: List[str]
    successive_year_blocked: bool
    provider_status: str
    created_at: str
    updated_at: str
    version: int


class CeCreditRecord(TypedDict):
    id: str
    originator_id: str
    ce_course_id: str
    completion_date: str
    reporting_period_year: int
    is_makeup: bool
    credit_hours: int
    category: str
    attributed_year: int
    credit_status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationPlan(TypedDict):
    id: str
    plan_name: str
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    base_basis_points: int
    min_fee_cents: int
    max_fee_cents: int
    salary_cents_per_period: int
    volume_tier_enabled: bool
    concession_absorption_enabled: bool
    status: str
    prohibited_variable_count: int
    assignment_effective_from: Optional[str]
    assignment_effective_to: Optional[str]
    assigned_originator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationVariable(TypedDict):
    id: str
    compensation_plan_id: str
    variable_type: str
    permissibility: str
    weight_pct: int
    justification_text: str
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict):
    id: str
    originator_id: str
    compensation_plan_id: Optional[str]
    state_code: str
    borrower_reference: str
    application_taken_at: str
    product_type: str
    requested_amount_cents: int
    par_rate_bps: int
    note_rate_bps: Optional[int]
    locked_amount_cents: Optional[int]
    funded_amount_cents: Optional[int]
    funded_at: Optional[str]
    payoff_date: Optional[str]
    lender_paid_comp_cents: int
    borrower_paid_comp_cents: int
    file_quality_score: int
    hours_worked_pct: int
    status: str
    compensation_status: str
    authority_flag: str
    closed_unit_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PricingException(TypedDict):
    id: str
    loan_application_id: str
    requested_by_user_id: str
    requested_rate_bps: int
    concession_cents: int
    reason_code: str
    justification_text: str
    status: str
    requires_second_approval: bool
    decided_by_user_id: Optional[str]
    second_decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    comp_impact_cents: int
    created_at: str
    updated_at: str
    version: int


class CompensationRecord(TypedDict):
    id: str
    loan_application_id: str
    originator_id: str
    compensation_plan_id: str
    variant: str
    tier_bps_adder: int
    base_comp_cents: int
    comp_impact_cents: int
    accrued_cents: int
    paid_cents: int
    clawback_cents: int
    days_held: Optional[int]
    recapture_pct: Optional[int]
    status: str
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Advertisement(TypedDict):
    id: str
    originator_id: str
    medium: str
    content_text: str
    disclosed_nmls_ids: List[str]
    disclosed_license_numbers: List[str]
    target_state_codes: List[str]
    status: str
    disclosure_findings: List[str]
    reviewed_by_user_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExaminationInquiry(TypedDict):
    id: str
    originator_id: Optional[str]
    state_code: str
    exam_reference: str
    opened_at: str
    response_due_at: str
    status: str
    response_round_count: int
    last_response_at: Optional[str]
    escalation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnlicensedActivityInvestigation(TypedDict):
    id: str
    originator_id: str
    loan_application_id: str
    opened_by: str
    detected_at: str
    trigger_reason: str
    status: str
    finding_by_user_id: Optional[str]
    restitution_cents: int
    remediated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict):
    """Append-only trail: carries only id and created_at (PRD 2.5)."""
    id: str
    subject_type: str
    subject_ref: str
    event_type: str
    actor_role: str
    actor_user_id: Optional[str]
    detail: str
    sequence_no: int
    created_at: str
