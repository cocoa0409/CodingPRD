"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    MEDICAL_DIRECTOR = "MedicalDirector"
    NURSE_STAFF = "NurseStaff"
    BILLING_SPECIALIST = "BillingSpecialist"


# --- Status enums ---
class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class ParticipantStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ELIGIBLE = "ELIGIBLE"
    ENROLLED = "ENROLLED"
    DISENROLLMENT_PENDING = "DISENROLLMENT_PENDING"
    DISENROLLED = "DISENROLLED"


class EnrollmentStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LevelOfCareStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    ACTIVE = "ACTIVE"
    REVISION = "REVISION"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class CarePlanGoalStatus(str, Enum):
    OPEN = "OPEN"
    MET = "MET"
    DISCONTINUED = "DISCONTINUED"


class AttendanceDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TransportLegStatus(str, Enum):
    PLANNED = "PLANNED"
    CANCELLED = "CANCELLED"


class TransportDirection(str, Enum):
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"


class MedicationOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    DISCONTINUED = "DISCONTINUED"


class MedicationOutcome(str, Enum):
    GIVEN = "GIVEN"
    REFUSED = "REFUSED"
    HELD = "HELD"


class CapitationPaymentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    RECONCILED = "RECONCILED"
    VOID = "VOID"


class ProrationMode(str, Enum):
    FULL_MONTH = "FULL_MONTH"
    DAILY = "DAILY"


class DisenrollmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FINALIZED = "FINALIZED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DisenrollmentKind(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY = "INVOLUNTARY"


class DisenrollmentReason(str, Enum):
    MOVED = "MOVED"
    DISSATISFIED = "DISSATISFIED"
    DECEASED = "DECEASED"
    LOSS_OF_ELIGIBILITY = "LOSS_OF_ELIGIBILITY"
    NONPAYMENT = "NONPAYMENT"
    DISRUPTIVE = "DISRUPTIVE"
    FRAUD = "FRAUD"


class Discipline(str, Enum):
    RN = "RN"
    SW = "SW"
    PT = "PT"
    DIETICIAN = "DIETICIAN"
    MEDICAL_DIRECTOR = "MEDICAL_DIRECTOR"


# --- Entity TypedDicts (common_fields: true unless noted) ---
class Program(TypedDict):
    id: str
    name: str
    state_code: str
    daily_census_capacity: int
    max_roster: int
    medicaid_monthly_rate_cents: int
    medicare_monthly_rate_cents: int
    medicare_only_supplement_cents: int
    lock_in_days: int
    loc_validity_days: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    program_id: str
    full_name: str
    date_of_birth: str
    dual_eligible: bool
    enrollment_effective_date: Optional[str]
    status: str
    active_loc_assessment_id: Optional[str]
    active_care_plan_id: Optional[str]
    active_enrollment_id: Optional[str]
    ledger_billed_cents: int
    ledger_reconciled_cents: int
    lifetime_attendance_days: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    participant_id: str
    enrollment_effective_date: str
    lock_in_end_date: str
    disenrollment_effective_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LevelOfCareAssessment(TypedDict):
    id: str
    participant_id: str
    nf_score: int
    nf_threshold: int
    assessed_on: str
    expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    participant_id: str
    supersedes_care_plan_id: Optional[str]
    idt_disciplines_signed: List[str]
    required_disciplines: List[str]
    goal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlanGoal(TypedDict):
    id: str
    care_plan_id: str
    discipline: str
    description: str
    target_attendance_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttendanceDay(TypedDict):
    id: str
    participant_id: str
    service_date: str
    meals_provided: int
    activities_count: int
    transport_required: bool
    transport_leg_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportLeg(TypedDict):
    id: str
    attendance_day_id: str
    direction: str
    window_start_min: int
    window_end_min: int
    vehicle_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict):
    id: str
    participant_id: str
    care_plan_id: str
    drug_name: str
    daily_doses: int
    administered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event record; carries ONLY id + created_at
class MedicationAdministration(TypedDict):
    id: str
    medication_order_id: str
    attendance_day_id: str
    outcome: str
    administered_at: str
    created_at: str


class CapitationPayment(TypedDict):
    id: str
    participant_id: str
    service_month: str
    medicaid_share_cents: int
    medicare_share_cents: int
    supplement_cents: int
    total_billed_cents: int
    proration_mode: str
    covered_days: int
    reconciled_cents: int
    recoup_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisenrollmentRequest(TypedDict):
    id: str
    participant_id: str
    kind: str
    reason_code: str
    requested_effective_date: str
    lock_in_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
