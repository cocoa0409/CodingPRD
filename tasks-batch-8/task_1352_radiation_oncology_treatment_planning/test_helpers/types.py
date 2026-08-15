"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    RADIATION_ONCOLOGIST = "RadiationOncologist"
    MEDICAL_DOSIMETRIST = "MedicalDosimetrist"
    MEDICAL_PHYSICIST = "MedicalPhysicist"
    RADIATION_THERAPIST = "RadiationTherapist"
    SCHEDULER = "Scheduler"
    BILLING_COORDINATOR = "BillingCoordinator"
    SYSTEM_ADMIN = "SystemAdmin"


class CourseStatus(str, Enum):
    CONSULT = "CONSULT"
    SIMULATION_SCHEDULED = "SIMULATION_SCHEDULED"
    SIMULATED = "SIMULATED"
    CONTOURING = "CONTOURING"
    PLANNING = "PLANNING"
    PHYSICS_REVIEW = "PHYSICS_REVIEW"
    TREATMENT_READY = "TREATMENT_READY"
    ON_TREATMENT = "ON_TREATMENT"
    ADAPTATION_REQUIRED = "ADAPTATION_REQUIRED"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


class SimulationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ContourStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PRIMARY_CHECK = "PENDING_PRIMARY_CHECK"
    PENDING_SECOND_CHECK = "PENDING_SECOND_CHECK"
    APPROVED_FOR_DELIVERY = "APPROVED_FOR_DELIVERY"
    ACTIVE = "ACTIVE"
    CHECK_FAILED = "CHECK_FAILED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class InterruptionStatus(str, Enum):
    OPEN = "OPEN"
    COMPENSATED = "COMPENSATED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUBMITTED = "SUBMITTED"


class MachineStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DOWN = "DOWN"


class Technique(str, Enum):
    THREE_DCRT = "THREE_DCRT"
    IMRT = "IMRT"
    SBRT = "SBRT"


class ChargeCode(str, Enum):
    SIMULATION = "SIMULATION"
    PLANNING = "PLANNING"
    PHYSICS_CHECK = "PHYSICS_CHECK"
    FRACTION_DELIVERY = "FRACTION_DELIVERY"
    IGRT = "IGRT"
    FIRST_FRACTION_SETUP = "FIRST_FRACTION_SETUP"
    NO_SHOW_FEE = "NO_SHOW_FEE"


# --- Entity TypedDicts ---
# Common-field entities carry id + created_at + updated_at + version.

class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class TreatmentCourse(TypedDict, total=False):
    id: str
    patient_id: str
    diagnosis_code: str
    intent: str
    technique: str
    prescribed_total_dose_cGy: int
    planned_fractions: int
    dose_per_fraction_cGy: int
    delivered_fractions: int
    delivered_dose_cGy: int
    fractions_since_chart_review: int
    baseline_weight_kg: Optional[float]
    weekend_makeup_allowance: int
    open_interruption_count: int
    bed_nominal_gy: float
    bed_actual_gy: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SimulationAppointment(TypedDict, total=False):
    id: str
    course_id: str
    machine_id: str
    purpose: str
    start_time: str
    end_time: str
    immobilization_device: str
    patient_weight_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContourSet(TypedDict, total=False):
    id: str
    course_id: str
    set_label: str
    target_volumes: List[str]
    oar_structures: List[str]
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict, total=False):
    id: str
    course_id: str
    contour_set_id: str
    supersedes_plan_id: Optional[str]
    plan_version: int
    target_total_dose_cGy: int
    planned_fractions: int
    dose_per_fraction_cGy: int
    planner_id: str
    pinned_contour_version: int
    primary_checker_id: Optional[str]
    secondary_checker_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseConstraint(TypedDict, total=False):
    id: str
    plan_id: str
    structure_name: str
    constraint_type: str
    limit_cGy: int
    evaluated_value_cGy: int
    satisfied: bool
    created_at: str
    updated_at: str
    version: int


class TreatmentMachine(TypedDict, total=False):
    id: str
    name: str
    machine_type: str
    room: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FractionSession(TypedDict, total=False):
    id: str
    course_id: str
    plan_id: str
    machine_id: str
    fraction_number: int
    start_time: str
    end_time: str
    igrt_planned: bool
    is_first_fraction: bool
    is_weekend: bool
    dose_delivered_cGy: Optional[int]
    cancellation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentInterruption(TypedDict, total=False):
    id: str
    course_id: str
    reason: str
    missed_count: int
    start_date: str
    end_date: str
    gap_days: int
    applied_strategy: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingClaim(TypedDict, total=False):
    id: str
    course_id: str
    status: str
    provisional_total_cents: int
    gross_total_cents: int
    discount_cents: int
    final_total_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only records (common_fields: false): id + created_at only,
# NO updated_at, NO version.

class PhysicsCheck(TypedDict, total=False):
    id: str
    plan_id: str
    check_type: str
    outcome: str
    checker_id: str
    notes: Optional[str]
    created_at: str


class ChartReview(TypedDict, total=False):
    id: str
    course_id: str
    reviewer_id: str
    outcome: str
    notes: Optional[str]
    delivered_fractions_at_review: int
    created_at: str


class ChargeLine(TypedDict, total=False):
    id: str
    claim_id: str
    code: str
    description: str
    quantity: int
    unit_charge_cents: int
    amount_cents: int
    event_ref_id: str
    created_at: str
