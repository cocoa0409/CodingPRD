"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    TRAINING_DIRECTOR = "TrainingDirector"
    VETERINARIAN = "Veterinarian"
    TRAINER = "Trainer"
    EVALUATOR = "Evaluator"
    APPLICANT = "Applicant"
    PUPPY_RAISER = "PuppyRaiser"


class PlacementTrack(str, Enum):
    MOBILITY = "MOBILITY"
    PTSD = "PTSD"
    AUTISM = "AUTISM"
    FACILITY = "FACILITY"


class TaskCode(str, Enum):
    RETRIEVE_ITEMS = "RETRIEVE_ITEMS"
    OPEN_DOORS = "OPEN_DOORS"
    BALANCE_SUPPORT = "BALANCE_SUPPORT"
    INTERRUPT_ANXIETY = "INTERRUPT_ANXIETY"
    ALERT_SOUND = "ALERT_SOUND"
    GUIDE_NAVIGATION = "GUIDE_NAVIGATION"
    DEEP_PRESSURE = "DEEP_PRESSURE"
    MEDICAL_ALERT = "MEDICAL_ALERT"


class ApplicantStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    WAITLISTED = "WAITLISTED"
    MATCH_ELIGIBLE = "MATCH_ELIGIBLE"
    MATCHED = "MATCHED"
    TEAM_TRAINING = "TEAM_TRAINING"
    PLACED = "PLACED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED_ACCEPTED = "FINALIZED_ACCEPTED"
    FINALIZED_REJECTED = "FINALIZED_REJECTED"


class WaitlistEntryStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    MATCHED = "MATCHED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ContributionStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class RaiserStatus(str, Enum):
    APPLIED = "APPLIED"
    VETTED = "VETTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    ON_HIATUS = "ON_HIATUS"
    INACTIVE = "INACTIVE"


class TrainerStatus(str, Enum):
    PROBATION = "PROBATION"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class DogStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_HEALTH_SCREENING = "IN_HEALTH_SCREENING"
    CLEARED = "CLEARED"
    RAISER_PLACED = "RAISER_PLACED"
    RECALLED = "RECALLED"
    IN_ADVANCED_TRAINING = "IN_ADVANCED_TRAINING"
    MATCH_READY = "MATCH_READY"
    MATCHED = "MATCHED"
    TEAM_TRAINING = "TEAM_TRAINING"
    PLACED = "PLACED"
    CAREER_CHANGED = "CAREER_CHANGED"
    RETIRED = "RETIRED"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class RaiserPlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EARLY_RETURN = "EARLY_RETURN"


class MilestoneCategory(str, Enum):
    OBEDIENCE = "OBEDIENCE"
    TASK_WORK = "TASK_WORK"
    PUBLIC_MANNERS = "PUBLIC_MANNERS"
    SOCIALIZATION = "SOCIALIZATION"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DISSOLVED = "DISSOLVED"
    COMPLETED = "COMPLETED"


class ClassStatus(str, Enum):
    PLANNED = "PLANNED"
    ENROLLING = "ENROLLING"
    IN_SESSION = "IN_SESSION"
    GRADUATION_REVIEW = "GRADUATION_REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    GRADUATED = "GRADUATED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"


class PatStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SCORED_PASS = "SCORED_PASS"
    SCORED_FAIL = "SCORED_FAIL"
    INVALIDATED = "INVALIDATED"


class PartnershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECERT_DUE = "RECERT_DUE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"
    DISSOLVED = "DISSOLVED"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class RecertificationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED_PASS = "COMPLETED_PASS"
    REMEDIATION = "REMEDIATION"
    FAILED_FINAL = "FAILED_FINAL"


class SupportRequestStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


# --- Entity TypedDicts (PRD §2.4: all entities carry id + created_at;
# all except TrainingMilestone also carry updated_at + version) ---


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    placement_track: str
    household_income_cents: int
    verified_income_cents: Optional[int]
    region: str
    application_status: str
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaskAssessment(TypedDict, total=False):
    id: str
    applicant_id: str
    required_tasks: List[str]
    task_urgency_tier: str
    home_environment_score: int
    status: str
    finalized_by_user_id: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    applicant_id: str
    status: str
    listed_at: str
    requirement_provisional_cents: int
    requirement_final_cents: Optional[int]
    effective_requirement_cents: int
    raised_cents: int
    dissolved_match_count: int
    rank_score: float
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    applicant_id: str
    donor_name: str
    amount_cents: int
    status: str
    created_by_user_id: str
    received_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PuppyRaiser(TypedDict, total=False):
    id: str
    full_name: str
    region: str
    foster_capacity: int
    experience_score: int
    status: str
    current_dog_count: int
    last_placement_ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trainer(TypedDict, total=False):
    id: str
    full_name: str
    pat_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Dog(TypedDict, total=False):
    id: str
    name: str
    origin: str
    breed: str
    sex: str
    born_on: str
    region: str
    sire_id: Optional[str]
    dam_id: Optional[str]
    donor_name: Optional[str]
    status: str
    clearance_score: Optional[int]
    primary_trainer_id: Optional[str]
    certified_tasks: List[str]
    career_change_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthScreening(TypedDict, total=False):
    id: str
    dog_id: str
    hip_grade: str
    elbow_grade: str
    eye_result: str
    cardiac_result: str
    genetic_panel: str
    clearance_score: int
    status: str
    veterinarian_user_id: str
    created_at: str
    updated_at: str
    version: int


class RaiserPlacement(TypedDict, total=False):
    id: str
    dog_id: str
    puppy_raiser_id: str
    started_on: str
    ended_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingMilestone(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version) — PRD §2.4.
    id: str
    dog_id: str
    category: str
    task_code: Optional[str]
    score: int
    recorded_at: str
    recorded_by_trainer_id: str
    rolling_avg_3: float
    cumulative_gate_score: float
    created_at: str


class MatchRecord(TypedDict, total=False):
    id: str
    dog_id: str
    waitlist_entry_id: str
    status: str
    proposed_by_user_id: str
    rank_score_at_match: float
    created_at: str
    updated_at: str
    version: int


class TeamTrainingClass(TypedDict, total=False):
    id: str
    name: str
    lead_trainer_id: str
    starts_on: str
    ends_on: str
    capacity: int
    total_sessions: int
    status: str
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    class_id: str
    match_id: str
    status: str
    sessions_attended: int
    attendance_pct: float
    created_at: str
    updated_at: str
    version: int


class PublicAccessTest(TypedDict, total=False):
    id: str
    enrollment_id: str
    evaluator_id: str
    scheduled_at: str
    location: Optional[str]
    attempt_number: int
    status: str
    exercise_scores: List[Dict[str, Any]]
    section_percents: Dict[str, float]
    official_score: float
    passed_gates: bool
    created_at: str
    updated_at: str
    version: int


class Partnership(TypedDict, total=False):
    id: str
    applicant_id: str
    dog_id: str
    enrollment_id: str
    status: str
    activated_at: str
    recert_due_at: str
    followups_completed: int
    last_recert_passed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FollowUp(TypedDict, total=False):
    id: str
    partnership_id: str
    due_on: str
    auto_generated: bool
    status: str
    outcome: Optional[str]
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Recertification(TypedDict, total=False):
    id: str
    partnership_id: str
    scheduled_on: str
    evaluator_id: str
    status: str
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportRequest(TypedDict, total=False):
    id: str
    partnership_id: str
    raised_by_applicant_id: str
    category: str
    description: str
    severity: str
    priority: Optional[str]
    status: str
    assigned_trainer_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
