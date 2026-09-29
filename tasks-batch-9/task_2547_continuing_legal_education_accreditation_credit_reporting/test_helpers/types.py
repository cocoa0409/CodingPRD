"""Domain types for the CLE Accreditation & Credit Reporting API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    BOARD_ADMIN = "BoardAdmin"
    ACCREDITATION_REVIEWER = "AccreditationReviewer"
    APPEALS_PANELIST = "AppealsPanelist"
    PROVIDER_ADMIN = "ProviderAdmin"
    ATTORNEY = "Attorney"


class ProviderType(str, Enum):
    BAR_ASSOCIATION = "BAR_ASSOCIATION"
    LAW_SCHOOL = "LAW_SCHOOL"
    GOVERNMENT = "GOVERNMENT"
    COMMERCIAL = "COMMERCIAL"
    LAW_FIRM = "LAW_FIRM"


class AccreditationStatus(str, Enum):
    APPLIED = "APPLIED"
    ACCREDITED = "ACCREDITED"
    PROBATIONARY = "PROBATIONARY"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    DENIED = "DENIED"


class AccreditationAction(str, Enum):
    GRANT_FULL = "GRANT_FULL"
    GRANT_PROBATIONARY = "GRANT_PROBATIONARY"
    DENY = "DENY"
    RENEW = "RENEW"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class RiskScoreVariant(str, Enum):
    REVIEWED_WEIGHTING = "REVIEWED_WEIGHTING"
    SELF_CERTIFIED_WEIGHTING = "SELF_CERTIFIED_WEIGHTING"


class DeliveryFormat(str, Enum):
    LIVE_IN_PERSON = "LIVE_IN_PERSON"
    LIVE_WEBCAST = "LIVE_WEBCAST"
    ON_DEMAND = "ON_DEMAND"
    SELF_STUDY = "SELF_STUDY"


class ApprovalPathway(str, Enum):
    PROVIDER_ACCREDITED = "PROVIDER_ACCREDITED"
    INDIVIDUAL_APPROVAL = "INDIVIDUAL_APPROVAL"


class CourseStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED_PENDING_REVIEW = "SUSPENDED_PENDING_REVIEW"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AttendanceVerificationMethod(str, Enum):
    ATTENDANCE_CODE = "ATTENDANCE_CODE"
    CERTIFICATE = "CERTIFICATE"
    ROSTER = "ROSTER"
    AFFIRMATION_ONLY = "AFFIRMATION_ONLY"


class CreditCategory(str, Enum):
    GENERAL = "GENERAL"
    ETHICS = "ETHICS"
    TECHNOLOGY = "TECHNOLOGY"
    BIAS_ELIMINATION = "BIAS_ELIMINATION"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    APPEAL_GRANTED = "APPEAL_GRANTED"
    APPEAL_DENIED = "APPEAL_DENIED"


class ReviewAction(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_INFO = "REQUEST_INFO"
    DENY = "DENY"


class AppellantAction(str, Enum):
    SUPPLEMENT = "SUPPLEMENT"
    APPEAL = "APPEAL"


class AttorneyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXEMPT = "EXEMPT"
    ADMIN_SUSPENDED = "ADMIN_SUSPENDED"
    INACTIVE = "INACTIVE"


class ComplianceGroup(str, Enum):
    GROUP_1 = "GROUP_1"
    GROUP_2 = "GROUP_2"
    GROUP_3 = "GROUP_3"


class CreditStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    DEFICIENT = "DEFICIENT"
    CLOSED_COMITY = "CLOSED_COMITY"


class AdministrativeStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    ADMIN_SUSPENDED = "ADMIN_SUSPENDED"
    REINSTATED = "REINSTATED"


class CarryoverElection(str, Enum):
    CARRY_FORWARD = "CARRY_FORWARD"
    WAIVE_CARRYOVER = "WAIVE_CARRYOVER"


class CureBasis(str, Enum):
    FEES_AND_CREDITS_CURED = "FEES_AND_CREDITS_CURED"
    BOARD_ORDER = "BOARD_ORDER"


class AffirmationType(str, Enum):
    ATTENDANCE_AFFIRMATION = "ATTENDANCE_AFFIRMATION"
    SELF_STUDY_AFFIRMATION = "SELF_STUDY_AFFIRMATION"
    FINAL_COMPLIANCE_AFFIRMATION = "FINAL_COMPLIANCE_AFFIRMATION"


class VerificationMethod(str, Enum):
    ATTENDANCE_CODE = "ATTENDANCE_CODE"
    CERTIFICATE = "CERTIFICATE"
    ROSTER = "ROSTER"
    AFFIRMATION = "AFFIRMATION"


class EffectiveFormat(str, Enum):
    LIVE = "LIVE"
    ON_DEMAND = "ON_DEMAND"
    SELF_STUDY = "SELF_STUDY"


class CreditSource(str, Enum):
    IN_STATE = "IN_STATE"
    RECIPROCITY = "RECIPROCITY"
    COMITY = "COMITY"


class CreditRecordStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class AdjudicationAction(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"
    VOID = "VOID"


class AttendanceReportStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    ACCEPTED_LATE = "ACCEPTED_LATE"


class ReciprocityBasis(str, Enum):
    RECIPROCITY = "RECIPROCITY"
    COMITY = "COMITY"


class OriginCategory(str, Enum):
    GENERAL = "GENERAL"
    PROFESSIONALISM = "PROFESSIONALISM"
    ETHICS = "ETHICS"
    TECHNOLOGY = "TECHNOLOGY"
    DIVERSITY_INCLUSION = "DIVERSITY_INCLUSION"


class ReciprocityClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AuditTriggerType(str, Enum):
    RISK_BASED = "RISK_BASED"
    COMPLAINT_ESCALATION = "COMPLAINT_ESCALATION"
    RANDOM = "RANDOM"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    SAMPLED = "SAMPLED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLEARED = "CLEARED"
    SANCTIONED = "SANCTIONED"


class AuditAction(str, Enum):
    DRAW_SAMPLE = "DRAW_SAMPLE"
    ISSUE_FINDINGS = "ISSUE_FINDINGS"
    CLOSE_CLEARED = "CLOSE_CLEARED"
    CLOSE_SANCTIONED = "CLOSE_SANCTIONED"


class SanctionType(str, Enum):
    NONE = "NONE"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"


class ComplaintSubjectType(str, Enum):
    PROVIDER = "PROVIDER"
    COURSE = "COURSE"


class AllegationCategory(str, Enum):
    MISREPRESENTED_CREDIT = "MISREPRESENTED_CREDIT"
    NO_SHOW_FACULTY = "NO_SHOW_FACULTY"
    ATTENDANCE_FRAUD = "ATTENDANCE_FRAUD"
    FEE_DISPUTE = "FEE_DISPUTE"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ComplaintAction(str, Enum):
    OPEN_REVIEW = "OPEN_REVIEW"
    SUBSTANTIATE = "SUBSTANTIATE"
    DISMISS = "DISMISS"


class ComplainantRole(str, Enum):
    ATTORNEY = "ATTORNEY"
    BOARD_ADMIN = "BOARD_ADMIN"


class FeeType(str, Enum):
    LATE_COMPLIANCE = "LATE_COMPLIANCE"
    REINSTATEMENT = "REINSTATEMENT"
    AUDIT_SANCTION = "AUDIT_SANCTION"
    PROVIDER_ANNUAL = "PROVIDER_ANNUAL"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class SettlementAction(str, Enum):
    PAY = "PAY"
    WAIVE = "WAIVE"


# --- Entity shapes -------------------------------------------------------
# Records carrying the common fields expose id, created_at, updated_at and
# version. The three append-only records (credit allocation, affirmation and
# reporting sweep) expose only id and created_at.


class Provider(TypedDict):
    id: str
    name: str
    provider_type: str
    accreditation_status: str
    accreditation_term_start: Optional[str]
    accreditation_term_end: Optional[str]
    self_certification_enabled: bool
    courses_total_count: int
    courses_self_certified_count: int
    attendance_reports_total_count: int
    attendance_reports_late_count: int
    substantiated_complaint_count: int
    audit_findings_count: int
    courses_sampled_lifetime: int
    last_audit_closed_at: Optional[str]
    risk_score: float
    risk_score_variant: str
    probation_reason: Optional[str]
    annual_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    provider_id: Optional[str]
    title: str
    delivery_format: str
    approval_pathway: str
    total_minutes: int
    presented_at: str
    expires_at: str
    status: str
    attendance_verification_method: str
    attendance_code: Optional[str]
    credited_minutes_total: int
    verified_credit_record_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditAllocation(TypedDict):
    id: str
    course_id: str
    category: str
    minutes: int
    created_at: str


class CourseApplication(TypedDict):
    id: str
    course_id: str
    applicant_role: str
    applicant_user_id: str
    status: str
    info_request_round: int
    supplement_count: int
    reviewer_user_id: Optional[str]
    denial_reason: Optional[str]
    appeal_grounds: Optional[str]
    appeal_panelist_user_id: Optional[str]
    appeal_filed_at: Optional[str]
    denied_at: Optional[str]
    decided_at: Optional[str]
    remand_count: int
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict):
    id: str
    bar_number: str
    full_name: str
    admission_date: str
    compliance_group: str
    status: str
    principal_office_jurisdiction: str
    outstanding_fee_cents: int
    open_deficiency_count: int
    pending_recertification_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceCycle(TypedDict):
    id: str
    attorney_id: str
    previous_cycle_id: Optional[str]
    comity_claim_id: Optional[str]
    period_start: str
    period_end: str
    filing_deadline: str
    required_total_minutes: int
    required_ethics_minutes: int
    required_technology_minutes: int
    required_bias_minutes: int
    prorated: bool
    carryover_in_general_minutes: int
    carryover_in_ethics_minutes: int
    carryover_out_general_minutes: int
    carryover_out_ethics_minutes: int
    earned_countable_minutes: int
    earned_ethics_minutes: int
    earned_technology_minutes: int
    earned_bias_minutes: int
    earned_live_minutes: int
    credit_status: str
    administrative_status: str
    delinquent_since: Optional[str]
    certified_at: Optional[str]
    carryover_election: str
    created_at: str
    updated_at: str
    version: int


class Affirmation(TypedDict):
    id: str
    cycle_id: str
    affirmation_type: str
    affirmed_by_user_id: str
    statement: str
    target_credit_record_id: Optional[str]
    created_at: str


class CreditRecord(TypedDict):
    id: str
    attorney_id: str
    cycle_id: str
    course_id: Optional[str]
    attendance_report_id: Optional[str]
    reciprocity_claim_id: Optional[str]
    affirmation_id: Optional[str]
    verification_method: str
    certificate_reference: Optional[str]
    attended_minutes: int
    completion_date: str
    credited_minutes: int
    credited_general_minutes: int
    credited_ethics_minutes: int
    credited_technology_minutes: int
    credited_bias_minutes: int
    countable_minutes: int
    effective_format: str
    source: str
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceReport(TypedDict):
    id: str
    course_id: str
    session_date: str
    session_end: str
    entries: List[dict]
    entry_count: int
    accepted_entry_count: int
    rejected_entry_count: int
    submitted_at: str
    days_late: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReciprocityClaim(TypedDict):
    id: str
    attorney_id: str
    basis: str
    origin_jurisdiction: str
    origin_course_title: str
    origin_credit_hours: float
    origin_category: str
    completion_date: str
    converted_minutes: int
    converted_category: str
    status: str
    determination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProviderAudit(TypedDict):
    id: str
    provider_id: str
    originating_complaint_id: Optional[str]
    audit_period_start: str
    audit_period_end: str
    trigger_type: str
    risk_score_at_open: float
    sample_size: int
    sampled_course_ids: List[str]
    findings_count: int
    status: str
    sanction_type: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    subject_type: str
    subject_id: str
    complainant_role: str
    complainant_user_id: str
    allegation: str
    allegation_category: str
    status: str
    disposition_reason: Optional[str]
    escalated: bool
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    attorney_id: Optional[str]
    cycle_id: Optional[str]
    provider_id: Optional[str]
    assessed_by_sweep_id: Optional[str]
    fee_type: str
    amount_cents: int
    status: str
    assessed_at: str
    settled_at: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReportingSweep(TypedDict):
    id: str
    sweep_number: int
    as_of: str
    cycles_examined: int
    delinquencies_issued: int
    suspensions_issued: int
    late_fees_assessed_cents: int
    courses_expired: int
    providers_lapsed: int
    created_at: str
