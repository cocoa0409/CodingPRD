"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class ProgramCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    RECERTIFICATION = "RECERTIFICATION"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"


class VolunteerStatus(str, Enum):
    TRAINEE = "TRAINEE"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    EXITED = "EXITED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DROPPED = "DROPPED"


class EntryKind(str, Enum):
    SERVICE = "SERVICE"
    CONTINUING_ED = "CONTINUING_ED"


class ActivityType(str, Enum):
    HELP_DESK = "HELP_DESK"
    OUTREACH = "OUTREACH"
    GARDEN = "GARDEN"
    PROJECT = "PROJECT"
    OTHER = "OTHER"


class CreditEntryStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SourceType(str, Enum):
    NONE = "NONE"
    PROJECT = "PROJECT"
    SHIFT = "SHIFT"
    ROTATION = "ROTATION"


class RecordStatus(str, Enum):
    PENDING = "PENDING"
    RECERTIFIED = "RECERTIFIED"
    SHORTFALL = "SHORTFALL"


class ShiftKind(str, Enum):
    HELP_DESK = "HELP_DESK"
    OUTREACH = "OUTREACH"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SignupStatus(str, Enum):
    SIGNED_UP = "SIGNED_UP"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class InquiryCategory(str, Enum):
    PLANT_ID = "PLANT_ID"
    PEST = "PEST"
    PLANT_DISEASE = "PLANT_DISEASE"
    SOIL = "SOIL"
    GENERAL = "GENERAL"


class InquiryStatus(str, Enum):
    LOGGED = "LOGGED"
    TRIAGED = "TRIAGED"
    REFERRED = "REFERRED"
    CLOSED = "CLOSED"


class InquiryResolution(str, Enum):
    NONE = "NONE"
    ANSWERED_AT_DESK = "ANSWERED_AT_DESK"
    SPECIALIST_DIAGNOSIS = "SPECIALIST_DIAGNOSIS"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    ANSWERED = "ANSWERED"
    RETURNED = "RETURNED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class RotationStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    SWAPPED = "SWAPPED"


class RecognitionTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    VOLUNTEER = "Volunteer"
    SPECIALIST = "Specialist"


class ProgramCycle(TypedDict, total=False):
    id: str
    year_label: str
    start_date: str
    end_date: str
    admission_capacity: int
    accepted_count: int
    hour_requirement: float
    ce_requirement: float
    training_module_count: int
    training_pass_quiz_average: float
    training_capacity: int
    enrolled_count: int
    recert_opens_at: str
    priority_counties: list
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    cycle_id: str
    applicant_name: str
    email: str
    county: str
    prior_gardening_years: int
    essay_score: Optional[int]
    interview_score: Optional[int]
    composite_score: Optional[float]
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    application_id: str
    full_name: str
    email: str
    status: str
    consecutive_shortfall_cycles: int
    no_show_strikes: int
    lifetime_base_hours: float
    recognition_tier: str
    recognition_points: float
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict, total=False):
    id: str
    cycle_id: str
    volunteer_id: str
    modules_completed: int
    quiz_average: float
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditEntry(TypedDict, total=False):
    id: str
    volunteer_id: str
    cycle_id: str
    entry_kind: str
    activity_type: Optional[str]
    provider: Optional[str]
    title: Optional[str]
    activity_date: str
    hours: float
    status: str
    source_type: str
    source_id: Optional[str]
    note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecertificationRecord(TypedDict, total=False):
    id: str
    volunteer_id: str
    cycle_id: str
    status: str
    hardship_exemption: bool
    exemption_reason: Optional[str]
    provisional_service_hours: float
    provisional_ce_hours: float
    official_service_hours: float
    official_ce_hours: float
    effective_hour_requirement: Optional[float]
    effective_ce_requirement: Optional[float]
    evaluated_at: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    cycle_id: str
    kind: str
    location: str
    start_time: str
    end_time: str
    capacity: int
    filled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftSignup(TypedDict, total=False):
    id: str
    shift_id: str
    volunteer_id: str
    status: str
    signed_up_at: str
    completed_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inquiry(TypedDict, total=False):
    id: str
    shift_id: str
    volunteer_id: str
    subject: str
    contact_name: str
    details: str
    category: Optional[str]
    status: str
    resolution: str
    answer_text: Optional[str]
    follow_up_of_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiagnosisReferral(TypedDict, total=False):
    id: str
    inquiry_id: str
    specialist_id: Optional[str]
    last_specialist_id: Optional[str]
    status: str
    due_at: str
    reassignment_count: int
    diagnosis_text: Optional[str]
    return_reason: Optional[str]
    answered_at: Optional[str]
    answered_by_specialist_id: Optional[str]
    returned_at: Optional[str]
    returned_by_specialist_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Specialist(TypedDict, total=False):
    id: str
    name: str
    specialty: str
    max_concurrent_referrals: int
    accepting_referrals: bool
    open_referral_count: int
    answered_count: int
    late_referral_count: int
    returned_count: int
    rolling_score: float
    lifetime_score: float
    created_at: str
    updated_at: str
    version: int


class CommunityProject(TypedDict, total=False):
    id: str
    cycle_id: str
    organizer_volunteer_id: str
    title: str
    description: str
    estimated_hours_per_volunteer: float
    max_creditable_hours_per_volunteer: Optional[float]
    approved_by_user_id: Optional[str]
    feedback: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RotationAssignment(TypedDict, total=False):
    id: str
    bed_code: str
    volunteer_id: str
    cycle_id: str
    week_start: str
    week_end: str
    status: str
    actual_hours: Optional[float]
    swapped_to_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
