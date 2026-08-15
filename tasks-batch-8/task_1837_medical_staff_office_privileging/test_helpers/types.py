"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §2.8, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COORDINATOR = "MedicalStaffCoordinator"
    COMMITTEE_CHAIR = "CredentialsCommitteeChair"
    MEC_CHAIR = "MedicalExecutiveCommitteeChair"
    BOARD_MEMBER = "BoardMember"
    DEPARTMENT_CHIEF = "DepartmentChief"
    PRACTITIONER = "Practitioner"
    HEARING_OFFICER = "HearingOfficer"


class MembershipStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    LAPSED = "LAPSED"


class PrivilegePosture(str, Enum):
    NONE = "NONE"
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    EMERGENCY_ONLY = "EMERGENCY_ONLY"


class ApplicationKind(str, Enum):
    INITIAL = "INITIAL"
    REAPPOINTMENT = "REAPPOINTMENT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PSV_IN_PROGRESS = "PSV_IN_PROGRESS"
    PSV_COMPLETE = "PSV_COMPLETE"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    BOARD_REVIEW = "BOARD_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class VerificationItemKind(str, Enum):
    MEDICAL_SCHOOL = "MEDICAL_SCHOOL"
    RESIDENCY = "RESIDENCY"
    BOARD_CERT = "BOARD_CERT"
    STATE_LICENSE = "STATE_LICENSE"
    DEA = "DEA"
    MALPRACTICE_HISTORY = "MALPRACTICE_HISTORY"
    WORK_HISTORY = "WORK_HISTORY"
    NPDB_QUERY = "NPDB_QUERY"
    REFERENCES = "REFERENCES"


class VerificationItemStatus(str, Enum):
    PENDING = "PENDING"
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    DISCREPANCY = "DISCREPANCY"
    WAIVED = "WAIVED"


class DelineationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CRITERIA_MET = "CRITERIA_MET"
    CRITERIA_UNMET = "CRITERIA_UNMET"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class GrantStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    RELINQUISHED = "RELINQUISHED"


class ReviewKind(str, Enum):
    FPPE = "FPPE"
    OPPE = "OPPE"


class ReviewStatus(str, Enum):
    COLLECTING = "COLLECTING"
    EVALUATION = "EVALUATION"
    PROVISIONAL_RESULT = "PROVISIONAL_RESULT"
    FINAL_RESULT = "FINAL_RESULT"
    CLOSED = "CLOSED"


class ReviewOutcome(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    MARGINAL = "MARGINAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class MetricDomain(str, Enum):
    CLINICAL_QUALITY = "CLINICAL_QUALITY"
    PATIENT_SAFETY = "PATIENT_SAFETY"
    DOCUMENTATION = "DOCUMENTATION"
    CITIZENSHIP = "CITIZENSHIP"
    UTILIZATION = "UTILIZATION"


class MetricStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"


class CredentialKind(str, Enum):
    STATE_LICENSE = "STATE_LICENSE"
    DEA = "DEA"
    BOARD_CERT = "BOARD_CERT"
    MALPRACTICE_INSURANCE = "MALPRACTICE_INSURANCE"
    ACLS = "ACLS"


class CredentialStatus(str, Enum):
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"
    RENEWED = "RENEWED"
    REVOKED = "REVOKED"


class TempKind(str, Enum):
    TEMPORARY = "TEMPORARY"
    EMERGENCY = "EMERGENCY"
    DISASTER = "DISASTER"


class TempStatus(str, Enum):
    PENDING_SPONSOR = "PENDING_SPONSOR"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED_EARLY = "TERMINATED_EARLY"


class CaseKind(str, Enum):
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"
    DENIAL_OF_REAPPOINTMENT = "DENIAL_OF_REAPPOINTMENT"
    RESTRICTION = "RESTRICTION"


class CaseStatus(str, Enum):
    PROPOSED = "PROPOSED"
    MEC_ENDORSED = "MEC_ENDORSED"
    HEARING_REQUESTED = "HEARING_REQUESTED"
    HEARING_HELD = "HEARING_HELD"
    REMANDED = "REMANDED"
    FINAL_ADVERSE = "FINAL_ADVERSE"
    FINAL_NO_ACTION = "FINAL_NO_ACTION"
    WITHDRAWN = "WITHDRAWN"


class HearingDecision(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    REMAND = "REMAND"


class PanelRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class PanelStatus(str, Enum):
    SEATED = "SEATED"
    RECUSED = "RECUSED"
    DISQUALIFIED = "DISQUALIFIED"


class NpdbReportKind(str, Enum):
    QUERY_INITIAL = "QUERY_INITIAL"
    QUERY_REAPPOINTMENT = "QUERY_REAPPOINTMENT"
    REPORT_ADVERSE_ACTION = "REPORT_ADVERSE_ACTION"
    REPORT_CORRECTION = "REPORT_CORRECTION"
    REPORT_VOID = "REPORT_VOID"


class NpdbReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    LATE = "LATE"
    VOIDED = "VOIDED"


class AgendaItemKind(str, Enum):
    APPLICATION_APPROVAL = "APPLICATION_APPROVAL"
    PRIVILEGE_GRANT = "PRIVILEGE_GRANT"
    ADVERSE_ACTION = "ADVERSE_ACTION"
    POLICY_CHANGE = "POLICY_CHANGE"


class CommitteeStatus(str, Enum):
    AGENDA = "AGENDA"
    COMMITTEE_APPROVED = "COMMITTEE_APPROVED"
    COMMITTEE_REJECTED = "COMMITTEE_REJECTED"
    MEC_ENDORSED = "MEC_ENDORSED"
    BOARD_RATIFIED = "BOARD_RATIFIED"
    BOARD_DECLINED = "BOARD_DECLINED"
    DEFERRED = "DEFERRED"


# ---------------------------------------------------------------------------
# Entity records — all carry id/created_at/updated_at/version per PRD §2.4
# except NpdbReport (immutable filing: only id + created_at).
# ---------------------------------------------------------------------------

class MedicalStaffMember(TypedDict, total=False):
    id: str
    full_name: str
    npdb_subject_id: str
    primary_specialty_code: str
    membership_status: str
    privilege_posture: str
    current_term_start: Optional[str]
    current_term_end: Optional[str]
    active_privilege_line_count: int
    credential_expiry_risk_score: float
    sod_exclusion_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class VolumeTier(TypedDict):
    tier_name: str
    min_cases: int
    score_multiplier: float


class SpecialtyCriteria(TypedDict, total=False):
    id: str
    specialty_code: str
    privilege_line: str
    min_training_months: int
    min_case_volume_24mo: int
    required_board_cert: bool
    fppe_case_count: int
    volume_tier_table: List[VolumeTier]
    created_at: str
    updated_at: str
    version: int


class AppointmentApplication(TypedDict, total=False):
    id: str
    member_id: str
    application_kind: str
    application_status: str
    submitted_at: Optional[str]
    verification_complete_count: int
    verification_required_count: int
    supersedes_application_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationItem(TypedDict, total=False):
    id: str
    application_id: str
    item_kind: str
    item_status: str
    requested_at: Optional[str]
    verified_at: Optional[str]
    discrepancy_note: Optional[str]
    waiver_justification: Optional[str]
    is_primary_source: bool
    created_at: str
    updated_at: str
    version: int


class PrivilegeDelineation(TypedDict, total=False):
    id: str
    application_id: str
    privilege_line: str
    documented_training_months: int
    documented_cases_24mo: int
    delineation_status: str
    satisfaction_tier: Optional[str]
    satisfaction_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PrivilegeGrant(TypedDict, total=False):
    id: str
    member_id: str
    delineation_id: str
    privilege_line: str
    grant_status: str
    effective_from: str
    effective_until: str
    fppe_cases_completed: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReview(TypedDict, total=False):
    id: str
    member_id: str
    privilege_grant_id: str
    review_kind: str
    review_status: str
    period_start: str
    period_end: str
    provisional_composite_score: Optional[float]
    final_composite_score: Optional[float]
    metric_count: int
    retracted_metric_count: int
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceMetric(TypedDict, total=False):
    id: str
    review_id: str
    metric_domain: str
    raw_value: float
    normalized_value: float
    domain_weight: float
    collected_at: str
    metric_status: str
    passed_fppe_case: bool
    created_at: str
    updated_at: str
    version: int


class ExpirableCredential(TypedDict, total=False):
    id: str
    member_id: str
    credential_kind: str
    credential_number: str
    issued_on: str
    expires_on: str
    credential_status: str
    supersedes_credential_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemporaryPrivilege(TypedDict, total=False):
    id: str
    member_id: str
    sponsor_member_id: str
    temp_kind: str
    privilege_line: str
    window_start: str
    window_end: str
    temp_status: str
    disaster_declaration_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdverseActionCase(TypedDict, total=False):
    id: str
    subject_member_id: str
    proposed_by_member_id: str
    case_kind: str
    case_status: str
    proposed_at: str
    hearing_request_deadline: str
    hearing_requested_at: Optional[str]
    npdb_reportable: bool
    restriction_days: int
    linked_review_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HearingPanel(TypedDict, total=False):
    id: str
    case_id: str
    panel_member_id: str
    panel_role: str
    panel_status: str
    seated_at: str
    created_at: str
    updated_at: str
    version: int


class NpdbReport(TypedDict, total=False):
    # Immutable filing record per PRD §2.4: carries ONLY id + created_at
    # from the standard system-managed set (no updated_at, no version).
    id: str
    member_id: str
    case_id: Optional[str]
    report_kind: str
    submitted_at: str
    submission_deadline: Optional[str]
    report_status: str
    is_late: bool
    created_at: str


class CommitteeAgendaItem(TypedDict, total=False):
    id: str
    item_kind: str
    ref_application_id: Optional[str]
    ref_delineation_id: Optional[str]
    ref_case_id: Optional[str]
    committee_status: str
    committee_votes_for: int
    committee_votes_against: int
    quorum_required: int
    mec_voter_ids: List[str]
    board_voter_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
