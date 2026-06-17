"""Domain types: entity TypedDicts, status enums, role enum.

Derived strictly from the Registered Apprenticeship Tracking PRD. Entities that
carry the common system fields expose id + created_at + updated_at + version;
the two immutable artifacts (CompletionCertificate, EEOReport) expose only
id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ─── Status enums ──────────────────────────────────────────────────────────
class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class JourneyworkerStatus(str, Enum):
    PROBATIONARY = "PROBATIONARY"
    QUALIFIED = "QUALIFIED"
    INACTIVE = "INACTIVE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OJTEntryStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RTIRecordStatus(str, Enum):
    RECORDED = "RECORDED"


class AttainmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CompletionType(str, Enum):
    HOURS_BASED = "HOURS_BASED"
    COMPETENCY_BASED = "COMPETENCY_BASED"
    HYBRID = "HYBRID"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    NONBINARY = "NONBINARY"
    UNDISCLOSED = "UNDISCLOSED"


class RaceEthnicity(str, Enum):
    HISPANIC = "HISPANIC"
    WHITE = "WHITE"
    BLACK = "BLACK"
    ASIAN = "ASIAN"
    NATIVE_AMERICAN = "NATIVE_AMERICAN"
    PACIFIC_ISLANDER = "PACIFIC_ISLANDER"
    TWO_OR_MORE = "TWO_OR_MORE"
    UNDISCLOSED = "UNDISCLOSED"


class CohortBasis(str, Enum):
    REGISTERED_COHORT = "REGISTERED_COHORT"
    ACTIVE_COHORT = "ACTIVE_COHORT"


class UserRole(str, Enum):
    REGISTRATION_AGENCY = "RegistrationAgency"
    SPONSOR = "Sponsor"
    TRAINING_COORDINATOR = "TrainingCoordinator"
    APPRENTICE = "Apprentice"


# ─── Entity TypedDicts (common_fields: true) ────────────────────────────────
class Sponsor(TypedDict):
    id: str
    legal_name: str
    ein: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class ApprenticeshipProgram(TypedDict):
    id: str
    sponsor_id: str
    occupation_code: str
    occupation_title: str
    completion_type: str
    ojt_hours_required: int
    rti_hours_required: int
    base_journeyworker_wage_cents: int
    journeyman_ratio: int
    active_agreement_count: int
    available_apprentice_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WageStep(TypedDict):
    id: str
    program_id: str
    step_number: int
    ojt_hours_threshold: int
    wage_pct: float
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    program_id: str
    sequence: int
    title: str
    required_for_completion: bool
    created_at: str
    updated_at: str
    version: int


class Journeyworker(TypedDict):
    id: str
    sponsor_id: str
    full_name: str
    active_apprentice_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Apprentice(TypedDict):
    id: str
    sponsor_id: str
    full_name: str
    gender: str
    race_ethnicity: str
    is_veteran: bool
    has_disability: bool
    created_at: str
    updated_at: str
    version: int


class ApprenticeAgreement(TypedDict):
    id: str
    program_id: str
    apprentice_id: str
    journeyworker_id: str
    start_date: str
    ojt_hours_completed: float
    rti_hours_completed: float
    milestones_attained_count: int
    current_wage_step: int
    current_hourly_wage_cents: int
    completion_eligible: bool
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OJTHoursEntry(TypedDict):
    id: str
    agreement_id: str
    work_date: str
    start_time: int
    end_time: int
    credited_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RTIRecord(TypedDict):
    id: str
    agreement_id: str
    course_code: str
    session_date: str
    instruction_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MilestoneAttainment(TypedDict):
    id: str
    agreement_id: str
    milestone_id: str
    attained_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Immutable artifacts (common_fields: false) — id + created_at only ──────
class CompletionCertificate(TypedDict):
    id: str
    agreement_id: str
    program_id: str
    occupation_code: str
    certified_ojt_hours: float
    certified_rti_hours: float
    issued_by_user_id: str
    created_at: str


class EEOReport(TypedDict):
    id: str
    program_id: str
    cohort_basis: str
    total_apprentices: int
    completed_count: int
    completion_rate_pct: float
    gender_distribution_pct: Dict[str, int]
    race_distribution_pct: Dict[str, int]
    veteran_count: int
    disability_count: int
    created_at: str
