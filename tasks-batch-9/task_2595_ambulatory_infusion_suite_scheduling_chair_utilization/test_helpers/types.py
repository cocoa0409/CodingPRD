"""Entity shapes, status enumerations and role names for the Infusion Suite API."""

from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role:
    SCHEDULER = "Scheduler"
    INFUSION_NURSE = "InfusionNurse"
    PHARMACIST = "Pharmacist"
    AUTHORIZATION_SPECIALIST = "AuthorizationSpecialist"
    MEDICAL_DIRECTOR = "MedicalDirector"
    PATIENT = "Patient"


ALL_ROLES = [
    Role.SCHEDULER,
    Role.INFUSION_NURSE,
    Role.PHARMACIST,
    Role.AUTHORIZATION_SPECIALIST,
    Role.MEDICAL_DIRECTOR,
    Role.PATIENT,
]

STAFF_ROLES = [
    Role.SCHEDULER,
    Role.INFUSION_NURSE,
    Role.PHARMACIST,
    Role.AUTHORIZATION_SPECIALIST,
    Role.MEDICAL_DIRECTOR,
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class ChairType:
    STANDARD = "STANDARD"
    BARIATRIC = "BARIATRIC"
    ISOLATION = "ISOLATION"


class ChairStatus:
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class NurseStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LotStatus:
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class DoseTier:
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class TemplateStatus:
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlanStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class ScheduleStatus:
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    INFUSING = "INFUSING"
    OBSERVING = "OBSERVING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


#: The five statuses over which chair committed minutes and nurse acuity are summed.
COMMITTED_SCHEDULE_STATUSES = [
    ScheduleStatus.TENTATIVE,
    ScheduleStatus.CONFIRMED,
    ScheduleStatus.CHECKED_IN,
    ScheduleStatus.INFUSING,
    ScheduleStatus.OBSERVING,
]

TERMINAL_SCHEDULE_STATUSES = [
    ScheduleStatus.COMPLETED,
    ScheduleStatus.CANCELLED,
    ScheduleStatus.NO_SHOW,
]


class ReadinessStatus:
    PENDING = "PENDING"
    AUTH_CLEARED = "AUTH_CLEARED"
    LAB_CLEARED = "LAB_CLEARED"
    FULLY_CLEARED = "FULLY_CLEARED"
    BLOCKED = "BLOCKED"


class BookingClass:
    ROUTINE = "ROUTINE"
    SAME_DAY_ADDON = "SAME_DAY_ADDON"
    URGENT = "URGENT"


class AuthStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PENDED = "PENDED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AuthDecision:
    APPROVED = "APPROVED"
    PENDED = "PENDED"
    DENIED = "DENIED"


class PreparationStatus:
    REQUESTED = "REQUESTED"
    PREPARED = "PREPARED"
    ADMINISTERED = "ADMINISTERED"
    WASTED = "WASTED"
    RETURNED = "RETURNED"


class AdverseEventStatus:
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class AdverseEventAction:
    SLOW_RATE = "SLOW_RATE"
    HOLD = "HOLD"
    ABORT = "ABORT"


class ReviewOutcome:
    RESUME_SAME_DRUG = "RESUME_SAME_DRUG"
    SWITCH_BIOSIMILAR = "SWITCH_BIOSIMILAR"
    DISCONTINUE = "DISCONTINUE"


class LabResultStatus:
    PENDING = "PENDING"
    RESULTED = "RESULTED"


class ReminderChannel:
    SMS = "SMS"
    VOICE = "VOICE"
    PORTAL = "PORTAL"


class ReminderOutcome:
    NO_RESPONSE = "NO_RESPONSE"
    CONFIRM_ATTENDANCE = "CONFIRM_ATTENDANCE"
    CANCEL_REQUEST = "CANCEL_REQUEST"


class ReminderTier:
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    INTENSIVE = "INTENSIVE"


class ReminderCadenceCode:
    C_STANDARD = "C_STANDARD"
    C_ELEVATED = "C_ELEVATED"
    C_INTENSIVE = "C_INTENSIVE"


class SteeringStatus:
    SUITE = "SUITE"
    HOME_INFUSION_REVIEW = "HOME_INFUSION_REVIEW"


class UtilizationVariant:
    SCHEDULED = "SCHEDULED"
    ACTUAL = "ACTUAL"


class RiskVariant:
    ROLLING_6 = "ROLLING_6"
    QUARTER_TO_DATE = "QUARTER_TO_DATE"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class InfusionCenter(TypedDict, total=False):
    id: str
    name: str
    open_minute: int
    close_minute: int
    turnover_buffer_minutes: int
    urgent_reserve_chair_count: int
    addon_cutoff_minute: int
    lab_validity_hours: int
    stagger_grid_minutes: int
    acuity_slot_minutes: int
    available_chair_count: int
    reserved_chair_count: int
    created_at: str
    updated_at: str
    version: int


class Chair(TypedDict, total=False):
    id: str
    center_id: str
    label: str
    chair_type: str
    status: str
    reserved_for_urgent: bool
    committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class Nurse(TypedDict, total=False):
    id: str
    center_id: str
    full_name: str
    acuity_capacity_points: int
    shift_start_minute: int
    shift_end_minute: int
    status: str
    assigned_acuity_points: int
    created_at: str
    updated_at: str
    version: int


class Drug(TypedDict, total=False):
    id: str
    name: str
    is_biosimilar: bool
    reference_drug_id: Optional[str]
    base_administration_minutes: int
    min_administration_minutes: int
    premedication_minutes: int
    observation_minutes_first_dose: int
    observation_minutes_subsequent: int
    acuity_points: int
    prep_stability_minutes: int
    unit_cost_cents: int
    requires_lab_gate: bool
    lab_min_anc: Optional[float]
    lab_min_platelets: Optional[float]
    created_at: str
    updated_at: str
    version: int


class DrugLot(TypedDict, total=False):
    id: str
    drug_id: str
    lot_number: str
    units_received: int
    expires_on: str
    units_committed: int
    units_administered: int
    units_wasted: int
    units_returned: int
    units_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    weight_kg: float
    completed_appointment_count: int
    no_show_strikes: int
    no_show_risk_score: float
    reminder_tier: str
    waste_liability_cents: int
    steering_status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict, total=False):
    id: str
    patient_id: str
    drug_id: str
    dose_mg_per_kg: float
    total_cycles: int
    premed_waived: bool
    status: str
    completed_cycles: int
    first_dose_completed: bool
    supersedes_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppointmentTemplate(TypedDict, total=False):
    id: str
    center_id: str
    drug_id: str
    dose_tier: str
    base_admin_minutes: int
    min_admin_minutes: int
    premed_minutes: int
    observation_minutes_first: int
    observation_minutes_subsequent: int
    acuity_points: int
    stagger_offset_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    center_id: str
    patient_id: str
    treatment_plan_id: str
    template_id: str
    chair_id: Optional[str]
    nurse_id: Optional[str]
    service_date: str
    requested_start_minute: int
    start_minute: int
    end_minute: int
    cycle_number: int
    booking_class: str
    schedule_status: str
    readiness_status: str
    premed_minutes: int
    admin_minutes: int
    observation_minutes: int
    observation_extension_minutes: int
    chair_minutes: int
    acuity_points: int
    template_version_pinned: int
    reminder_cadence_code: str
    actual_start_minute: Optional[int]
    actual_end_minute: Optional[int]
    billable_chair_units: Optional[int]
    cancellation_charge_cents: int
    late_cancellation: bool
    rescheduled_from_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuthorizationRequest(TypedDict, total=False):
    id: str
    appointment_id: str
    treatment_plan_id: str
    payer_name: str
    status: str
    submission_count: int
    approved_units: Optional[int]
    decision_reason: Optional[str]
    decided_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrugPreparation(TypedDict, total=False):
    id: str
    appointment_id: str
    drug_lot_id: str
    units_requested: int
    status: str
    prepared_at: Optional[str]
    usable_until: Optional[str]
    waste_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict, total=False):
    id: str
    appointment_id: str
    reported_by_nurse_id: str
    grade: int
    action: str
    note: Optional[str]
    observation_extension_minutes: int
    status: str
    review_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict, total=False):
    """Laboratory draws are immutable: only ``id`` and ``created_at`` audit fields."""

    id: str
    patient_id: str
    collected_at: str
    anc_value: Optional[float]
    platelet_value: Optional[float]
    status: str
    created_at: str


class ReminderContact(TypedDict, total=False):
    id: str
    appointment_id: str
    patient_id: str
    channel: str
    sequence_number: int
    sent_at: str
    outcome: str
    created_at: str
    updated_at: str
    version: int
