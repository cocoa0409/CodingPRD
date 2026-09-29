"""Domain types for the Placement Testing and Corequisite Remediation API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Every one of the twelve persisted resource types carries the four
system-managed properties described in PRD §2.4 (``id``, ``created_at``,
``updated_at``, ``version``).
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    ASSESSMENT_DIRECTOR = "AssessmentDirector"
    ASSESSMENT_STAFF = "AssessmentStaff"
    PROCTOR = "Proctor"
    INSTRUCTOR = "Instructor"
    REGISTRAR = "Registrar"
    STUDENT = "Student"


# --------------------------------------------------------------------------- #
# Shared enumerations
# --------------------------------------------------------------------------- #
class SubjectArea(str, Enum):
    MATH = "MATH"
    ENGLISH = "ENGLISH"
    ESL = "ESL"
    OTHER = "OTHER"


class RaceEthnicityCode(str, Enum):
    AIAN = "AIAN"
    ASIAN = "ASIAN"
    BLACK = "BLACK"
    HISPANIC = "HISPANIC"
    MULTI = "MULTI"
    NHPI = "NHPI"
    WHITE = "WHITE"
    UNKNOWN = "UNKNOWN"


class ElStatus(str, Enum):
    NOT_EL = "NOT_EL"
    EL_ACTIVE = "EL_ACTIVE"
    EL_EXITED = "EL_EXITED"


class HsTranscriptStatus(str, Enum):
    NONE = "NONE"
    SELF_REPORTED = "SELF_REPORTED"
    VERIFIED = "VERIFIED"


class SelfGuidedPathway(str, Enum):
    STEM = "STEM"
    BSTEM = "BSTEM"
    NON_STEM = "NON_STEM"


class PlacementStatus(str, Enum):
    UNPLACED = "UNPLACED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class MeasureType(str, Enum):
    TRANSCRIPT_GPA = "TRANSCRIPT_GPA"
    TEST_SCORE = "TEST_SCORE"
    SELF_GUIDED = "SELF_GUIDED"


class MeasureTypeUsed(str, Enum):
    TRANSCRIPT_GPA = "TRANSCRIPT_GPA"
    TEST_SCORE = "TEST_SCORE"
    SELF_GUIDED = "SELF_GUIDED"
    APPEAL_OVERRIDE = "APPEAL_OVERRIDE"


class RequisiteType(str, Enum):
    PREREQUISITE = "PREREQUISITE"
    COREQUISITE = "COREQUISITE"
    ADVISORY = "ADVISORY"


class Enforcement(str, Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


class MinGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    P = "P"


class FinalGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"
    P = "P"
    NP = "NP"
    W = "W"


class VoidReason(str, Enum):
    IRREGULARITY = "IRREGULARITY"
    PROCTOR_ERROR = "PROCTOR_ERROR"
    ADMIN_CORRECTION = "ADMIN_CORRECTION"


class DenialReason(str, Enum):
    PLACEMENT_SUPERSEDED = "PLACEMENT_SUPERSEDED"
    EVIDENCE_DISPUTED = "EVIDENCE_DISPUTED"
    SECTION_CANCELLED = "SECTION_CANCELLED"


class AppealGrounds(str, Enum):
    NEW_TRANSCRIPT = "NEW_TRANSCRIPT"
    TEST_IRREGULARITY = "TEST_IRREGULARITY"
    EL_PATHWAY = "EL_PATHWAY"
    OTHER = "OTHER"


class AppealDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class StudyDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DisaggregationKey(str, Enum):
    RACE_ETHNICITY = "RACE_ETHNICITY"
    EL_STATUS = "EL_STATUS"
    FIRST_GENERATION = "FIRST_GENERATION"
    PELL = "PELL"


# --------------------------------------------------------------------------- #
# Per-entity status / state enumerations
# --------------------------------------------------------------------------- #
class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CourseRequisiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlacementRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class TestAdministrationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TestAttemptState(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    SCORED = "SCORED"
    VOIDED = "VOIDED"
    NO_SHOW = "NO_SHOW"


class PlacementState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    APPEALED = "APPEALED"
    SUPERSEDED = "SUPERSEDED"


class EvidenceState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class PlacementAppealState(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    INSTRUCTOR_ENDORSED = "INSTRUCTOR_ENDORSED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class SectionStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PairingState(str, Enum):
    UNPAIRED = "UNPAIRED"
    PAIRED = "PAIRED"
    PAIR_BROKEN = "PAIR_BROKEN"


class RoleInPair(str, Enum):
    NONE = "NONE"
    PRIMARY = "PRIMARY"
    SUPPORT = "SUPPORT"


class RegistrationState(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"
    DROPPED = "DROPPED"
    COMPLETED = "COMPLETED"


class PrerequisiteStatus(str, Enum):
    SATISFIED = "SATISFIED"
    OVERRIDDEN = "OVERRIDDEN"
    UNMET = "UNMET"


class PrerequisiteOverrideState(str, Enum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ValidationStudyState(str, Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------- #
# Entity TypedDicts — all twelve carry id/created_at/updated_at/version
# --------------------------------------------------------------------------- #
class Student(TypedDict):
    id: str
    student_number: str
    full_name: str
    race_ethnicity_code: str
    first_generation: bool
    pell_eligible: bool
    el_status: str
    hs_gpa: Optional[float]
    transcript_recorded_at: Optional[str]
    hs_transcript_status: str
    self_guided_pathway: Optional[str]
    attempt_counts: dict
    remaining_attempts: dict
    placement_status: str
    advising_hold: bool
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    course_code: str
    title: str
    subject_area: str
    level_rank: int
    units: float
    is_support_course: bool
    transfer_level: bool
    status: str
    enrolled_count: int
    success_count: int
    success_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CourseRequisite(TypedDict):
    id: str
    course_id: str
    requisite_course_id: str
    requisite_type: str
    min_grade: str
    enforcement: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlacementRule(TypedDict):
    id: str
    subject_area: str
    measure_type: str
    target_course_id: str
    coreq_course_id: Optional[str]
    coreq_required: bool
    priority_rank: int
    min_hs_gpa: Optional[float]
    max_hs_gpa: Optional[float]
    min_score: Optional[int]
    max_score: Optional[int]
    required_el_status: Optional[str]
    required_self_guided_pathway: Optional[str]
    effective_from: str
    effective_to: Optional[str]
    version_label: str
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestAdministration(TypedDict):
    id: str
    room_code: str
    subject_area: str
    proctor_user_id: str
    starts_at: str
    ends_at: str
    seat_capacity: int
    duration_minutes: int
    seats_booked: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestAttempt(TypedDict):
    id: str
    student_id: str
    administration_id: str
    subject_area: str
    attempt_ordinal: int
    raw_score: Optional[int]
    scaled_score: Optional[int]
    irregularity_flag: bool
    scored_at: Optional[str]
    next_eligible_at: Optional[str]
    void_reason: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class PlacementDetermination(TypedDict):
    id: str
    student_id: str
    subject_area: str
    measure_type_used: str
    applied_rule_id: Optional[str]
    placed_course_id: str
    coreq_course_id: Optional[str]
    source_attempt_id: Optional[str]
    superseded_by_id: Optional[str]
    base_confidence_score: float
    staleness_penalty: float
    confidence_score: float
    validity_days: int
    expires_at: str
    determined_by_user_id: str
    determined_at: str
    placement_state: str
    evidence_state: str
    created_at: str
    updated_at: str
    version: int


class PlacementAppeal(TypedDict):
    id: str
    determination_id: str
    student_id: str
    requested_course_id: str
    grounds: str
    statement: str
    revision_round: int
    info_request_note: Optional[str]
    reviewed_by_user_id: Optional[str]
    endorsed_by_user_id: Optional[str]
    decision_note: Optional[str]
    filed_at: str
    decided_at: Optional[str]
    minted_determination_id: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict):
    id: str
    course_id: str
    term_code: str
    room_code: str
    meets_start_at: str
    meets_end_at: str
    seat_capacity: int
    seats_taken: int
    seats_held: int
    waitlist_count: int
    available_seats: int
    linked_section_id: Optional[str]
    role_in_pair: str
    pairing_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    student_id: str
    section_id: str
    coreq_registration_id: Optional[str]
    override_id: Optional[str]
    prerequisite_status: str
    term_units_at_confirm: Optional[float]
    final_grade: Optional[str]
    graded_at: Optional[str]
    success: bool
    denial_reason: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class PrerequisiteOverride(TypedDict):
    id: str
    student_id: str
    course_id: str
    requisite_id: str
    justification: str
    expires_at: str
    issued_by_user_id: str
    consumed_by_registration_id: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class CutScoreValidationStudy(TypedDict):
    id: str
    subject_area: str
    candidate_rule_id: str
    window_start_at: str
    window_end_at: str
    strict_cohort_size: int
    strict_success_count: int
    strict_success_rate: Optional[float]
    inclusive_cohort_size: int
    inclusive_success_count: int
    inclusive_success_rate: Optional[float]
    disproportionate_impact_index: Optional[float]
    reference_group_key: Optional[str]
    run_count: int
    proposed_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int
