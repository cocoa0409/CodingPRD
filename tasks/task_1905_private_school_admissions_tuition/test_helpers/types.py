"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ADMISSION_DIRECTOR = "AdmissionDirector"
    ADMISSION_OFFICER = "AdmissionOfficer"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    PARENT = "Parent"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    EARLY_CLOSED = "EARLY_CLOSED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class GradeLevel(str, Enum):
    K = "K"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"
    G9 = "G9"
    G10 = "G10"
    G11 = "G11"
    G12 = "G12"


class ApplicationRound(str, Enum):
    EARLY = "EARLY"
    REGULAR = "REGULAR"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EVALUATION_COMPLETE = "EVALUATION_COMPLETE"
    OFFERED = "OFFERED"
    CONTRACT_ISSUED = "CONTRACT_ISSUED"
    WAITLISTED = "WAITLISTED"
    ENROLLED = "ENROLLED"
    DENIED = "DENIED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    MELTED = "MELTED"


class EvaluationKind(str, Enum):
    TEST = "TEST"
    INTERVIEW = "INTERVIEW"


class EvaluationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SCORED = "SCORED"
    CANCELLED = "CANCELLED"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StudentSource(str, Enum):
    DIRECT = "DIRECT"
    ADMISSION = "ADMISSION"


class VerificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class AwardStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    APPEALED = "APPEALED"
    RELEASED = "RELEASED"


class ContractStatus(str, Enum):
    ISSUED = "ISSUED"
    SIGNED = "SIGNED"
    ENROLLED = "ENROLLED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    MELTED = "MELTED"


class ReenrollmentOfferStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    LAPSED = "LAPSED"
    SUPERSEDED = "SUPERSEDED"


# All ten resources carry the common system fields id/created_at/updated_at/version
# (PRD §2.5); TypedDicts below list them once each for clarity.

class AdmissionCycle(TypedDict):
    id: str
    academic_year: str
    early_deadline_at: str
    regular_deadline_at: str
    reenroll_response_deadline_at: str
    melt_deadline_at: str
    aid_budget_total_cents: int
    aid_committed_cents: int
    pacing_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GradeSection(TypedDict):
    id: str
    cycle_id: str
    grade_level: str
    capacity: int
    tuition_cents: int
    max_aid_seat_pct: float
    seats_held: int
    aid_seats_held: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    family_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    legacy_parent: bool
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    family_id: str
    first_name: str
    last_name: str
    current_grade_section_id: str
    status: str
    source: str
    re_enrolled_for_cycle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    cycle_id: str
    grade_section_id: str
    round: str
    status: str
    submitted_at: Optional[str]
    composite_score: Optional[float]
    preference_points: int
    sibling_verified: bool
    offer_expires_at: Optional[str]
    promoted_from_waitlist: bool
    estimated_deposit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EntranceEvaluation(TypedDict):
    id: str
    application_id: str
    kind: str
    scheduled_start: str
    scheduled_end: str
    interviewer_id: Optional[str]
    test_session_id: Optional[str]
    score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestSession(TypedDict):
    id: str
    cycle_id: str
    session_start: str
    session_end: str
    room_capacity: int
    booked_count: int
    created_at: str
    updated_at: str
    version: int


class AidApplication(TypedDict):
    id: str
    application_id: str
    reported_annual_income_cents: int
    household_size: int
    verified_annual_income_cents: Optional[int]
    verified_by_user_id: Optional[str]
    verification_status: str
    provisional_award_cents: int
    final_award_cents: Optional[int]
    award_status: str
    appeal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnrollmentContract(TypedDict):
    id: str
    application_id: str
    tuition_cents: int
    award_cents: int
    net_tuition_cents: int
    deposit_amount_cents: int
    paid_cents: int
    response_due_at: str
    created_student_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReenrollmentOffer(TypedDict):
    id: str
    student_id: str
    cycle_id: str
    prior_tuition_cents: int
    new_tuition_cents: int
    sibling_discount_cents: int
    discounted_tuition_cents: int
    response_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
