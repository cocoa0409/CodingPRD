"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ADMIN = "Admin"
    INTAKE = "Intake"
    CLINICIAN = "Clinician"
    DIETITIAN = "Dietitian"
    UTILIZATION_REVIEWER = "UtilizationReviewer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OccupancyPosture(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class LevelOfCare(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    PHP = "PHP"
    IOP = "IOP"
    OP = "OP"


class AgeBand(str, Enum):
    ADOLESCENT = "ADOLESCENT"
    ADULT = "ADULT"


class MedicalStabilityPosture(str, Enum):
    STABLE = "STABLE"
    GUARDED = "GUARDED"
    UNSTABLE = "UNSTABLE"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class ClinicalStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    PENDING_ADMISSION = "PENDING_ADMISSION"
    ADMITTED = "ADMITTED"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    DISCHARGE_PENDING = "DISCHARGE_PENDING"
    DISCHARGED = "DISCHARGED"
    ADMINISTRATIVE_DISCHARGE = "ADMINISTRATIVE_DISCHARGE"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVISION = "REVISION"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class Discipline(str, Enum):
    THERAPY = "THERAPY"
    DIETITIAN = "DIETITIAN"
    MEDICAL = "MEDICAL"


class MealPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SupervisionLevel(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class MealType(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"
    SNACK = "SNACK"


class FamilyProgramStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class DischargePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class AftercareLevelOfCare(str, Enum):
    PHP = "PHP"
    IOP = "IOP"
    OP = "OP"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Full-record entities carry id + created_at + updated_at + version.
# The meal event is the sole append-only log: id + created_at only.
# ---------------------------------------------------------------------------
class Facility(TypedDict):
    id: str
    name: str
    timezone: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    facility_id: str
    level_of_care: str
    bed_capacity: int
    beds_occupied: int
    beds_available: int
    occupancy_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    program_id: str
    facility_id: str
    name: str
    age_band: str
    slot_capacity: int
    slots_filled: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    facility_id: str
    full_name: str
    age_band: str
    bmi: float
    medical_stability_posture: str
    nutritional_risk_score: float
    provisional_nutritional_risk_score: float
    active_assessment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    patient_id: str
    facility_id: str
    medical_severity: int
    behavioral_severity: int
    psychiatric_severity: int
    motivation_level: int
    composite_score: float
    recommended_level_of_care: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict):
    id: str
    patient_id: str
    facility_id: str
    program_id: str
    cohort_id: str
    requested_length_of_stay_days: int
    clinical_status: str
    level_of_care: Optional[str]
    admitted_at_iso: Optional[str]
    loc_entered_at_iso: Optional[str]
    discharged_at_iso: Optional[str]
    waitlist_promoted: bool
    created_at: str
    updated_at: str
    version: int


class InsuranceAuthorization(TypedDict):
    id: str
    admission_id: str
    facility_id: str
    payer_name: str
    daily_rate_cents: int
    coinsurance_pct: float
    days_authorized: int
    days_consumed: int
    days_remaining: int
    covered_through_iso: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConcurrentReview(TypedDict):
    id: str
    authorization_id: str
    facility_id: str
    decision: str
    window_start_iso: Optional[str]
    window_end_iso: Optional[str]
    approved_days: int
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    admission_id: str
    facility_id: str
    therapy_signed: bool
    dietitian_signed: bool
    medical_signed: bool
    goals_total: int
    goals_met: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MealPlan(TypedDict):
    id: str
    admission_id: str
    facility_id: str
    required_meals_per_day: int
    supervision_level: str
    meals_logged: int
    completion_points: float
    meal_compliance_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only log: id + created_at only (no updated_at, no version).
class MealEvent(TypedDict):
    id: str
    meal_plan_id: str
    admission_id: str
    meal_type: str
    completion_fraction: float
    refused: bool
    logged_at_iso: str
    created_at: str


class FamilyProgramEnrollment(TypedDict):
    id: str
    admission_id: str
    facility_id: str
    family_contact_name: str
    sessions_required: int
    sessions_completed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DischargePlan(TypedDict):
    id: str
    admission_id: str
    facility_id: str
    aftercare_level_of_care: str
    relapse_warning_signs: str
    relapse_plan_complete: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingSummary(TypedDict):
    authorization_id: str
    days_consumed: int
    days_remaining: int
    patient_responsibility_cents: int
