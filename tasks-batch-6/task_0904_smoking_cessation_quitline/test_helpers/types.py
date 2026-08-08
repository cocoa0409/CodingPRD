"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CASE_MANAGER = "CaseManager"
    PARTICIPANT = "Participant"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class EmployerProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    PENDING_ASSESSMENT = "PENDING_ASSESSMENT"
    ACTIVE = "ACTIVE"
    DISENROLLED = "DISENROLLED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"


class ReadinessResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class NrtEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXHAUSTED = "EXHAUSTED"


class QuitAttemptStatus(str, Enum):
    COMMITTED = "COMMITTED"
    QUIT_ACHIEVED = "QUIT_ACHIEVED"
    RELAPSED = "RELAPSED"
    ABANDONED = "ABANDONED"


class QuitMethod(str, Enum):
    COLD_TURKEY = "COLD_TURKEY"
    NRT_ASSISTED = "NRT_ASSISTED"
    MEDICATION = "MEDICATION"
    GRADUAL_REDUCTION = "GRADUAL_REDUCTION"


class CoachingCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELED = "CANCELED"


class MedicationType(str, Enum):
    PATCH = "PATCH"
    GUM = "GUM"
    LOZENGE = "LOZENGE"
    VARENICLINE = "VARENICLINE"
    BUPROPION = "BUPROPION"


class NrtShipmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELED = "CANCELED"
    RETURNED = "RETURNED"


class MilestoneType(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    QUIT_DATE_SET = "QUIT_DATE_SET"
    SEVEN_DAY_ABSTINENT = "SEVEN_DAY_ABSTINENT"
    THIRTY_DAY_ABSTINENT = "THIRTY_DAY_ABSTINENT"
    PROTOCOL_COMPLETE = "PROTOCOL_COMPLETE"
    DISCRETIONARY = "DISCRETIONARY"


class AwardStatus(str, Enum):
    EARNED = "EARNED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class AwardSource(str, Enum):
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class ReferralType(str, Enum):
    PROVIDER = "PROVIDER"
    BENEFIT = "BENEFIT"
    PHARMACY = "PHARMACY"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CoachingProtocol(str, Enum):
    STANDARD = "STANDARD"
    INTENSIVE = "INTENSIVE"


# --------------------------------------------------------------------------
# Entity TypedDicts — versioned entities carry id/created_at/updated_at/version
# --------------------------------------------------------------------------
class EmployerProgram(TypedDict):
    id: str
    name: str
    budget_total_cents: int
    budget_remaining_cents: int
    coaching_protocol: str
    nrt_courses_allotted: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    full_name: str
    languages: List[str]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    full_name: str
    email: str
    primary_language: str
    cigarettes_per_day: int
    employer_program_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    participant_id: str
    status: str
    readiness_score: Optional[int]
    readiness_result: Optional[str]
    nrt_courses_allotted: int
    nrt_courses_used: int
    nrt_courses_remaining: int
    nrt_eligibility: str
    incentive_earned_cents: int
    completed_calls: int
    protocol_complete: bool
    created_at: str
    updated_at: str
    version: int


class QuitAttempt(TypedDict):
    id: str
    enrollment_id: str
    quit_date: str
    method: str
    status: str
    attempt_number: int
    created_at: str
    updated_at: str
    version: int


class CoachingCall(TypedDict):
    id: str
    enrollment_id: str
    coach_id: str
    scheduled_start: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NRTShipment(TypedDict):
    id: str
    enrollment_id: str
    medication_type: str
    course_start_date: str
    course_end_date: str
    weeks_supply: int
    dose_mg: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveAward(TypedDict):
    id: str
    enrollment_id: str
    milestone_type: str
    amount_cents: int
    status: str
    source: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    enrollment_id: str
    referral_type: str
    target_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only clinical events — carry ONLY id + created_at (no version/updated_at)
# --------------------------------------------------------------------------
class ReadinessAssessment(TypedDict):
    id: str
    enrollment_id: str
    motivation_score: int
    confidence_score: int
    prior_quit_attempts: int
    cigarettes_per_day: int
    readiness_score: int
    result: str
    created_at: str


class FollowUpOutcome(TypedDict):
    id: str
    enrollment_id: str
    day: int
    abstinent: bool
    recorded_at: str
    created_at: str
