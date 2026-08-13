"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class Specialty(str, Enum):
    INTERNAL_MEDICINE = "INTERNAL_MEDICINE"
    SURGERY = "SURGERY"
    CARDIOLOGY = "CARDIOLOGY"
    PEDIATRICS = "PEDIATRICS"
    EMERGENCY_MEDICINE = "EMERGENCY_MEDICINE"
    ANESTHESIOLOGY = "ANESTHESIOLOGY"
    OBSTETRICS = "OBSTETRICS"
    PSYCHIATRY = "PSYCHIATRY"


class UserRole(str, Enum):
    QUALITY_DIRECTOR = "QualityDirector"
    PEER_REVIEW_COORDINATOR = "PeerReviewCoordinator"
    COMMITTEE_MEMBER = "CommitteeMember"
    PROVIDER = "Provider"


class MemberRole(str, Enum):
    MEMBER = "MEMBER"
    CHAIR = "CHAIR"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CaseStatus(str, Enum):
    REFERRED = "REFERRED"
    SCREENED_IN = "SCREENED_IN"
    SCREENED_OUT = "SCREENED_OUT"
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    DELIBERATION = "DELIBERATION"
    NOTIFIED = "NOTIFIED"
    RESPONDED = "RESPONDED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    CLOSED = "CLOSED"
    EXTERNAL_REVIEW = "EXTERNAL_REVIEW"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    WAIVED = "WAIVED"


class DeliberationStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class Rating(str, Enum):
    APPROPRIATE = "APPROPRIATE"
    MINOR_OFI = "MINOR_OFI"
    MAJOR_OFI = "MAJOR_OFI"
    UNACCEPTABLE = "UNACCEPTABLE"


class FocusedReviewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class TriggerType(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class ConflictType(str, Enum):
    PRIOR_TREATING = "PRIOR_TREATING"
    FAMILY = "FAMILY"
    FINANCIAL = "FINANCIAL"
    SUPERVISORY = "SUPERVISORY"
    OTHER = "OTHER"


class ConflictSource(str, Enum):
    SELF_DECLARED = "SELF_DECLARED"
    AUTO_CASE_RESOLVED = "AUTO_CASE_RESOLVED"


class ReferralSource(str, Enum):
    INCIDENT_REPORT = "INCIDENT_REPORT"
    PATIENT_COMPLAINT = "PATIENT_COMPLAINT"
    STAFF_REFERRAL = "STAFF_REFERRAL"
    INSURER_INQUIRY = "INSURER_INQUIRY"
    OTHER = "OTHER"


class ScreenedOutReason(str, Enum):
    DUPLICATE = "DUPLICATE"
    FRIVOLOUS = "FRIVOLOUS"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    OTHER = "OTHER"


# --- Primary resources (PRD §2.4: id, created_at, updated_at, version) ---


class Provider(TypedDict, total=False):
    id: str
    full_name: str
    specialty: str
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict, total=False):
    id: str
    provider_id: str
    specialty: str
    member_role: str
    status: str
    reliability_completed_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewCase(TypedDict, total=False):
    id: str
    subject_provider_id: str
    referral_source: str
    referred_at: str
    description: str
    status: str
    screened_out_reason: Optional[str]
    screened_out_at: Optional[str]
    focus_group_id: Optional[str]
    closure_basis: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewAssignment(TypedDict, total=False):
    id: str
    case_id: str
    reviewer_id: str
    sequence: int
    status: str
    care_appropriateness_score: Optional[int]
    ofi_score: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deliberation(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    rating: Optional[str]
    rationale_note: Optional[str]
    reconsideration_note: Optional[str]
    opened_at: str
    finalized_at: Optional[str]
    reconsidered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FocusedReview(TypedDict, total=False):
    id: str
    provider_id: str
    trigger_type: str
    basis: Optional[str]
    trigger_snapshot: Optional[dict]
    status: str
    opened_at: str
    closed_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FocusGroup(TypedDict, total=False):
    id: str
    focus_id: str
    name: str
    created_at: str
    updated_at: str
    version: int


# --- Immutable ledger-style records (PRD §2.4: only id and created_at) ---


class ConflictDeclaration(TypedDict, total=False):
    id: str
    member_id: str
    provider_id: str
    conflict_type: str
    source: str
    created_at: str


class CaseNote(TypedDict, total=False):
    id: str
    case_id: str
    author_member_id: str
    body: str
    note_type: str
    created_at: str


class ProviderNotification(TypedDict, total=False):
    id: str
    case_id: str
    sent_at: str
    response_deadline: str
    created_at: str


class ProviderResponse(TypedDict, total=False):
    id: str
    case_id: str
    response_text: str
    submitted_at: str
    created_at: str


class ExternalReferral(TypedDict, total=False):
    id: str
    case_id: str
    reason: str
    referred_at: str
    created_at: str


class FocusGroupMember(TypedDict, total=False):
    id: str
    focus_group_id: str
    member_id: str
    created_at: str
