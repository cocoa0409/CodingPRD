"""Domain types for the Thesis Format Review & Deposit API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    STUDENT = "Student"
    FACULTY_MEMBER = "FacultyMember"
    GRAD_SCHOOL_ANALYST = "GradSchoolAnalyst"
    GRADUATE_DEAN = "GraduateDean"
    INTEGRITY_OFFICER = "IntegrityOfficer"
    REGISTRAR = "Registrar"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------


class TermStatus(str, Enum):
    OPEN = "OPEN"
    DEPOSIT_CLOSED = "DEPOSIT_CLOSED"
    CONFERRED = "CONFERRED"


class DegreeLevel(str, Enum):
    MASTERS = "MASTERS"
    DOCTORAL = "DOCTORAL"


class DocumentType(str, Enum):
    THESIS = "THESIS"
    DISSERTATION = "DISSERTATION"


class AppointmentType(str, Enum):
    TENURED = "TENURED"
    TENURE_TRACK = "TENURE_TRACK"
    ADJUNCT = "ADJUNCT"
    EXTERNAL = "EXTERNAL"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class ThesisWorkflowState(str, Enum):
    DRAFT = "DRAFT"
    COMMITTEE_PENDING = "COMMITTEE_PENDING"
    COMMITTEE_APPROVED = "COMMITTEE_APPROVED"
    DEFENSE_SCHEDULED = "DEFENSE_SCHEDULED"
    DEFENSE_ANNOUNCED = "DEFENSE_ANNOUNCED"
    DEFENSE_PASSED = "DEFENSE_PASSED"
    DEFENSE_PASSED_WITH_REVISIONS = "DEFENSE_PASSED_WITH_REVISIONS"
    DEFENSE_FAILED = "DEFENSE_FAILED"
    UNDER_FORMAT_REVIEW = "UNDER_FORMAT_REVIEW"
    FORMAT_REVISIONS_REQUIRED = "FORMAT_REVISIONS_REQUIRED"
    FORMAT_ACCEPTED = "FORMAT_ACCEPTED"
    DEPOSITED = "DEPOSITED"
    CONFERRED = "CONFERRED"
    TERMINATED = "TERMINATED"


class ThesisIntegrityState(str, Enum):
    NOT_SCREENED = "NOT_SCREENED"
    SCREEN_CLEARED = "SCREEN_CLEARED"
    SCREEN_FLAGGED = "SCREEN_FLAGGED"
    UNDER_INTEGRITY_REVIEW = "UNDER_INTEGRITY_REVIEW"
    INTEGRITY_CLEARED = "INTEGRITY_CLEARED"
    INTEGRITY_UPHELD = "INTEGRITY_UPHELD"


class CommitteeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISSOLVED = "DISSOLVED"


class CommitteeSeatRole(str, Enum):
    CHAIR = "CHAIR"
    CO_CHAIR = "CO_CHAIR"
    MEMBER = "MEMBER"
    EXTERNAL_MEMBER = "EXTERNAL_MEMBER"
    GRADUATE_REPRESENTATIVE = "GRADUATE_REPRESENTATIVE"


class CommitteeSeatStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class DefenseEventStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    HELD_PASS = "HELD_PASS"
    HELD_PASS_WITH_REVISIONS = "HELD_PASS_WITH_REVISIONS"
    HELD_FAIL = "HELD_FAIL"
    CANCELLED = "CANCELLED"


class DefenseOutcome(str, Enum):
    PASS = "PASS"
    PASS_WITH_REVISIONS = "PASS_WITH_REVISIONS"
    FAIL = "FAIL"


class FormatReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REVISIONS_REQUIRED = "REVISIONS_REQUIRED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class FormatReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN_REVISIONS = "RETURN_REVISIONS"


class EmbargoStatus(str, Enum):
    REQUESTED = "REQUESTED"
    MORE_INFO_REQUIRED = "MORE_INFO_REQUIRED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class EmbargoReasonCode(str, Enum):
    PATENT_PENDING = "PATENT_PENDING"
    PUBLISHER_AGREEMENT = "PUBLISHER_AGREEMENT"
    SENSITIVE_DATA = "SENSITIVE_DATA"
    HUMAN_SUBJECTS = "HUMAN_SUBJECTS"


class EmbargoDecision(str, Enum):
    APPROVE = "APPROVE"
    PARTIALLY_APPROVE = "PARTIALLY_APPROVE"
    DENY = "DENY"
    REQUEST_INFO = "REQUEST_INFO"


class EmbargoReleaseAnchor(str, Enum):
    DEPOSIT = "DEPOSIT"
    CONFERRAL = "CONFERRAL"


class PermissionMaterialType(str, Enum):
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    EXCERPT = "EXCERPT"
    PREVIOUSLY_PUBLISHED_CHAPTER = "PREVIOUSLY_PUBLISHED_CHAPTER"
    DATASET = "DATASET"


class PermissionRightsBasis(str, Enum):
    WRITTEN_PERMISSION = "WRITTEN_PERMISSION"
    FAIR_USE_ASSERTION = "FAIR_USE_ASSERTION"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    OPEN_LICENSE = "OPEN_LICENSE"


class PermissionRecordStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"
    WAIVED = "WAIVED"


class PermissionReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DEFICIENT = "DEFICIENT"
    WAIVE = "WAIVE"


class IntegrityScreeningStatus(str, Enum):
    SCREENED = "SCREENED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    REFERRED = "REFERRED"
    DISMISSED = "DISMISSED"
    UPHELD = "UPHELD"
    SUPERSEDED = "SUPERSEDED"


class IntegrityAction(str, Enum):
    REFER = "REFER"
    DISMISS = "DISMISS"
    UPHOLD = "UPHOLD"


class DepositStatus(str, Enum):
    DEPOSITED = "DEPOSITED"
    WITHDRAWN = "WITHDRAWN"


class AccessLevel(str, Enum):
    OPEN_ACCESS = "OPEN_ACCESS"
    CAMPUS_ONLY = "CAMPUS_ONLY"
    EMBARGOED = "EMBARGOED"


class ClearanceStatus(str, Enum):
    BLOCKED = "BLOCKED"
    PENDING_ITEMS = "PENDING_ITEMS"
    CLEARED = "CLEARED"
    CONFERRED = "CONFERRED"
    WITHHELD = "WITHHELD"


class ProjectionVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ClearanceItem(str, Enum):
    COMMITTEE_APPROVAL = "COMMITTEE_APPROVAL"
    DEFENSE_OUTCOME = "DEFENSE_OUTCOME"
    PERMISSIONS = "PERMISSIONS"
    FORMAT_ACCEPTANCE = "FORMAT_ACCEPTANCE"
    EMBARGO_DECISION = "EMBARGO_DECISION"
    INTEGRITY = "INTEGRITY"
    DEPOSIT = "DEPOSIT"


# The fixed emission order of the clearance projection (PRD §3.9).
CLEARANCE_ITEM_ORDER: List[str] = [
    ClearanceItem.COMMITTEE_APPROVAL.value,
    ClearanceItem.DEFENSE_OUTCOME.value,
    ClearanceItem.PERMISSIONS.value,
    ClearanceItem.FORMAT_ACCEPTANCE.value,
    ClearanceItem.EMBARGO_DECISION.value,
    ClearanceItem.INTEGRITY.value,
    ClearanceItem.DEPOSIT.value,
]


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id/created_at/updated_at/version
# --------------------------------------------------------------------------


class Term(TypedDict):
    id: str
    code: str
    defense_deadline: str
    format_review_deposit_deadline: str
    degree_conferral_date: str
    announcement_lead_business_days: int
    status: str
    conferred_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    email: str
    degree_level: str
    program_code: str
    graduation_clearance_state: str
    degree_conferred: bool
    transcript_notation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacultyMember(TypedDict):
    id: str
    full_name: str
    email: str
    appointment_type: str
    graduate_faculty_certified: bool
    active_chair_load: int
    created_at: str
    updated_at: str
    version: int


class DefenseRoom(TypedDict):
    id: str
    code: str
    building: str
    seat_capacity: int
    turnover_buffer_minutes: int
    status: str
    booked_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class Thesis(TypedDict):
    id: str
    student_id: str
    term_id: str
    title: str
    document_type: str
    page_count: int
    third_party_item_count: int
    workflow_state: str
    integrity_state: str
    format_cycle_count: int
    documented_permission_count: int
    analyst_turnaround_bdays_total: int
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict):
    id: str
    thesis_id: str
    status: str
    member_count: int
    external_member_count: int
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    rejection_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict):
    id: str
    committee_id: str
    faculty_id: str
    role: str
    status: str
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefenseEvent(TypedDict):
    id: str
    thesis_id: str
    room_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    announced_at: Optional[str]
    announcement_lead_bdays: Optional[int]
    outcome: Optional[str]
    outcome_note: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormatReview(TypedDict):
    id: str
    thesis_id: str
    cycle_number: int
    status: str
    opened_at: str
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision: Optional[str]
    critical_defect_count: int
    major_defect_count: int
    minor_defect_count: int
    severity_weighted_defect_score: float
    revision_due_at: Optional[str]
    turnaround_bdays: Optional[int]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmbargoRequest(TypedDict):
    id: str
    thesis_id: str
    reason_code: str
    requested_months: int
    justification: str
    status: str
    approved_months: Optional[int]
    info_request_count: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    release_date: Optional[str]
    release_anchor: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermissionRecord(TypedDict):
    id: str
    thesis_id: str
    material_type: str
    rights_basis: str
    page_reference: str
    excerpt_word_count: int
    document_uri: Optional[str]
    status: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntegrityScreening(TypedDict):
    id: str
    thesis_id: str
    similarity_pct: float
    excluded_quoted_pct: float
    adjusted_similarity_pct: float
    status: str
    screened_at: str
    referred_at: Optional[str]
    referred_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepositoryDeposit(TypedDict):
    id: str
    thesis_id: str
    handle: str
    abstract_word_count: int
    subject_keywords: List[str]
    advisor_name: Optional[str]
    department_code: Optional[str]
    metadata_completeness_score: float
    access_level: str
    embargo_release_date: Optional[str]
    late_fee_cents: int
    status: str
    deposited_at: str
    depositor_user_id: str
    created_at: str
    updated_at: str
    version: int


class GraduationClearance(TypedDict):
    id: str
    student_id: str
    status: str
    projection_variant: str
    outstanding_items: List[str]
    cleared_at: Optional[str]
    conferral_posted_at: Optional[str]
    transcript_notation: Optional[str]
    withheld_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
