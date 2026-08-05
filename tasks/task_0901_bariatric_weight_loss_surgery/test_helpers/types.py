"""Domain types: entity TypedDicts, status enums, role enum.

All types derive from the Bariatric Weight-Loss Surgery Program PRD. Every entity
carries the full common-field set (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    DIETITIAN = "Dietitian"
    BEHAVIORAL_HEALTH_CLINICIAN = "BehavioralHealthClinician"
    BILLING_SPECIALIST = "BillingSpecialist"
    SURGEON = "Surgeon"
    SYSTEM_ADMIN = "SystemAdmin"


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class PaymentPathway(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"


class CandidacyStatus(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class QualifyingReason(str, Enum):
    BMI_40_PLUS = "BMI_40_PLUS"
    BMI_35_PLUS_COMORBIDITY = "BMI_35_PLUS_COMORBIDITY"
    NOT_MET = "NOT_MET"


class ProgramStatus(str, Enum):
    SCREENING = "SCREENING"
    CANDIDACY_REVIEW = "CANDIDACY_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    CLEARANCE_IN_PROGRESS = "CLEARANCE_IN_PROGRESS"
    CLEARED = "CLEARED"
    SURGERY_SCHEDULED = "SURGERY_SCHEDULED"
    POST_OP = "POST_OP"
    READMITTED = "READMITTED"
    COMPLETED = "COMPLETED"


class PsychStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DEFERRED = "DEFERRED"


class NutritionDecision(str, Enum):
    CLEARED = "CLEARED"
    NOT_CLEARED = "NOT_CLEARED"


class MilestoneCode(str, Enum):
    NUTRITION_CLASS = "NUTRITION_CLASS"
    EXERCISE_ORIENTATION = "EXERCISE_ORIENTATION"
    SURGERY_RISKS_CONSENT = "SURGERY_RISKS_CONSENT"
    POST_OP_DIET_EDUCATION = "POST_OP_DIET_EDUCATION"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ProcedureType(str, Enum):
    SLEEVE_GASTRECTOMY = "SLEEVE_GASTRECTOMY"
    GASTRIC_BYPASS = "GASTRIC_BYPASS"
    ADJUSTABLE_BAND = "ADJUSTABLE_BAND"


class SurgeryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ComplicationType(str, Enum):
    LEAK = "LEAK"
    BLEEDING = "BLEEDING"
    STRICTURE = "STRICTURE"
    INFECTION = "INFECTION"
    DVT = "DVT"
    OTHER = "OTHER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ComplicationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class IntervalCode(str, Enum):
    WEEK_2 = "WEEK_2"
    WEEK_6 = "WEEK_6"
    MONTH_3 = "MONTH_3"
    MONTH_6 = "MONTH_6"
    MONTH_12 = "MONTH_12"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class FinancingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# ----- Entity TypedDicts (all entities carry common fields) -----

class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    sex: str
    height_cm: float
    baseline_weight_kg: float
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    plan_name: str
    payer_code: str
    required_supervised_diet_months: int
    requires_psych_clearance: bool
    requires_nutrition_clearance: bool
    bmi_floor_no_comorbidity: float
    bmi_floor_with_comorbidity: float
    qualifying_comorbidities: List[str]
    created_at: str
    updated_at: str
    version: int


class OperatingRoom(TypedDict):
    id: str
    room_code: str
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Surgeon(TypedDict):
    id: str
    full_name: str
    npi: str
    credentialed_procedures: List[str]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    patient_id: str
    payment_pathway: str
    insurance_plan_id: Optional[str]
    comorbidities: List[str]
    baseline_bmi: float
    baseline_weight_kg: float
    ideal_body_weight_kg: float
    candidacy_status: str
    qualifying_reason: Optional[str]
    status: str
    clearances_complete: bool
    readmission_count: int
    active_complication_count: int
    amount_collected_cents: int
    amount_refunded_cents: int
    amount_forfeited_cents: int
    created_at: str
    updated_at: str
    version: int


class SupervisedDietVisit(TypedDict):
    id: str
    program_id: str
    month_index: int
    visit_date: str
    weight_kg: float
    attended: bool
    created_at: str
    updated_at: str
    version: int


class PsychEvaluation(TypedDict):
    id: str
    program_id: str
    clinician_note: Optional[str]
    status: str
    deferral_reason: Optional[str]
    reevaluation_count: int
    created_at: str
    updated_at: str
    version: int


class NutritionClearance(TypedDict):
    id: str
    program_id: str
    decision: str
    diet_readiness_score: int
    created_at: str
    updated_at: str
    version: int


class EducationMilestone(TypedDict):
    id: str
    program_id: str
    milestone_code: str
    completed: bool
    completed_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurgeryCase(TypedDict):
    id: str
    program_id: str
    operating_room_id: str
    surgeon_id: str
    procedure_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    estimated_bundle_cents: int
    actual_or_minutes: Optional[int]
    final_bundle_cents: Optional[int]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complication(TypedDict):
    id: str
    surgery_case_id: str
    complication_type: str
    severity: str
    requires_readmission: bool
    onset_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpVisit(TypedDict):
    id: str
    program_id: str
    interval_code: str
    scheduled_date: str
    status: str
    recorded_weight_kg: Optional[float]
    ewl_pct_ibw: Optional[float]
    ewl_pct_bmi25: Optional[float]
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    program_id: str
    procedure_type: str
    down_payment_cents: int
    term_months: int
    apr_bps: int
    bundle_price_cents: int
    interest_cents: int
    installment_cents: int
    final_installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
