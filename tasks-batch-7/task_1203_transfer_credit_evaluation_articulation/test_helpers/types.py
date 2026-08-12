"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the standard system-managed fields (id, created_at,
updated_at, version) per the PRD's common-resource-properties section.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    REGISTRAR_ADMIN = "RegistrarAdmin"
    TRANSFER_CENTER_STAFF = "TransferCenterStaff"
    TRANSFER_EVALUATOR = "TransferEvaluator"
    FACULTY_ADJUDICATOR = "FacultyAdjudicator"
    STUDENT = "Student"


class CreditSystem(str, Enum):
    SEMESTER = "SEMESTER"
    QUARTER = "QUARTER"


class CourseLevel(str, Enum):
    LOWER = "LOWER"
    UPPER = "UPPER"
    GRADUATE = "GRADUATE"


class GenEdTag(str, Enum):
    GENED_COMMS = "GENED_COMMS"
    GENED_MATH = "GENED_MATH"
    GENED_SCIENCE = "GENED_SCIENCE"
    GENED_HUMANITIES = "GENED_HUMANITIES"
    GENED_SOCIAL = "GENED_SOCIAL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class EquivalencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EquivalencyType(str, Enum):
    DIRECT = "DIRECT"
    GENED_ONLY = "GENED_ONLY"
    ELECTIVE = "ELECTIVE"


class TranscriptStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    EXTRACTED = "EXTRACTED"
    REJECTED = "REJECTED"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    EVALUATED = "EVALUATED"
    POSTED = "POSTED"


class LineItemStatus(str, Enum):
    PENDING = "PENDING"
    AUTO_MATCHED = "AUTO_MATCHED"
    PETITION_REQUIRED = "PETITION_REQUIRED"
    ADOPTED = "ADOPTED"
    DENIED = "DENIED"
    POSTED = "POSTED"


class LineItemResolution(str, Enum):
    AUTO_EQUIVALENCY = "AUTO_EQUIVALENCY"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    PETITION = "PETITION"
    AUTO_GRADE = "AUTO_GRADE"


class PetitionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class PlaStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    CREDITED = "CREDITED"
    REJECTED = "REJECTED"


class PlaSourceType(str, Enum):
    MILITARY_JST = "MILITARY_JST"
    CLEP = "CLEP"
    AP = "AP"
    IB = "IB"
    PORTFOLIO = "PORTFOLIO"


class RequirementSlot(str, Enum):
    MAJOR_CORE = "MAJOR_CORE"
    MAJOR_ELECTIVE = "MAJOR_ELECTIVE"
    GENED_COMMS = "GENED_COMMS"
    GENED_MATH = "GENED_MATH"
    GENED_SCIENCE = "GENED_SCIENCE"
    GENED_HUMANITIES = "GENED_HUMANITIES"
    GENED_SOCIAL = "GENED_SOCIAL"
    FREE_ELECTIVE = "FREE_ELECTIVE"


class RequirementApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    PARTIAL = "PARTIAL"
    UNAPPLIED = "UNAPPLIED"


class TransferGuideStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class PartnerInstitution(TypedDict, total=False):
    id: str
    name: str
    institution_code: str
    credit_system: str
    state_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InternalCourse(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    credit_hours: float
    level: str
    department: str
    gened_tags: List[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class ArticulationAgreement(TypedDict, total=False):
    id: str
    partner_institution_id: str
    program_scope: str
    effective_start: str
    effective_end: str
    amends_agreement_id: Optional[str]
    status: str
    activated_at: Optional[str]
    expired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourseEquivalency(TypedDict, total=False):
    id: str
    agreement_id: str
    internal_course_id: str
    external_course_code: str
    external_title: str
    external_credit_hours: float
    effective_from: str
    effective_until: str
    equivalency_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferStudent(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    declared_major: str
    catalog_year: int
    total_posted_transfer_credits: float
    total_posted_pla_credits: float
    created_at: str
    updated_at: str
    version: int


class TranscriptCourse(TypedDict, total=False):
    external_course_code: str
    title: str
    credit_hours: float
    grade: str


class Transcript(TypedDict, total=False):
    id: str
    student_id: str
    partner_institution_id: str
    term_completed: str
    courses: List[TranscriptCourse]
    status: str
    rejection_reason: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferCreditEvaluation(TypedDict, total=False):
    id: str
    student_id: str
    transcript_id: str
    status: str
    provisional_credits_total: float
    awarded_credits_total: float
    applied_credits_total: float
    open_line_count: int
    evaluated_by_id: Optional[str]
    posted_by_id: Optional[str]
    posted_at: Optional[str]
    reopen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvaluationLineItem(TypedDict, total=False):
    id: str
    evaluation_id: str
    external_course_code: str
    external_title: str
    external_credit_hours: float
    grade: str
    grade_points: float
    equivalency_id: Optional[str]
    internal_course_id: Optional[str]
    provisional_credits: Optional[float]
    awarded_credits: Optional[float]
    applied_credits: Optional[float]
    status: str
    resolution: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict, total=False):
    id: str
    line_item_id: str
    student_id: str
    proposed_internal_course_id: str
    syllabus_ref: str
    status: str
    adjudicator_id: Optional[str]
    adjudication_note: Optional[str]
    awarded_internal_course_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    petition_id: str
    student_id: str
    grounds: str
    status: str
    adjudicator_id: Optional[str]
    adjudication_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriorLearningAssessment(TypedDict, total=False):
    id: str
    student_id: str
    source_type: str
    credential_ref: str
    claimed_credits: float
    verified_credits: Optional[float]
    proposed_internal_course_id: Optional[str]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RequirementApplication(TypedDict, total=False):
    id: str
    student_id: str
    line_item_id: Optional[str]
    pla_id: Optional[str]
    slot: str
    applied_credits: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferGuide(TypedDict, total=False):
    id: str
    partner_institution_id: str
    catalog_year: int
    status: str
    pinned_agreement_id: Optional[str]
    pinned_agreement_version: Optional[int]
    published_at: Optional[str]
    entries_snapshot: Optional[List[Any]]
    is_stale: bool
    created_at: str
    updated_at: str
    version: int
