"""Domain types for the Vision Therapy & Developmental Optometry API.

Status enums, role enum and entity TypedDicts, named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    OPTOMETRIST = "Optometrist"
    VISION_THERAPIST = "VisionTherapist"
    THERAPY_ASSISTANT = "TherapyAssistant"
    BILLING_SPECIALIST = "BillingSpecialist"
    FRONT_DESK = "FrontDesk"
    PATIENT_USER = "PatientUser"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class DiagnosisCategory(str, Enum):
    CONVERGENCE_INSUFFICIENCY = "CONVERGENCE_INSUFFICIENCY"
    ACCOMMODATIVE_DYSFUNCTION = "ACCOMMODATIVE_DYSFUNCTION"
    OCULOMOTOR_DYSFUNCTION = "OCULOMOTOR_DYSFUNCTION"
    AMBLYOPIA = "AMBLYOPIA"


class PatientClinicalStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


class DischargeReason(str, Enum):
    GOALS_MET = "GOALS_MET"
    PLATEAU = "PLATEAU"
    NON_COMPLIANCE = "NON_COMPLIANCE"
    TRANSFERRED = "TRANSFERRED"
    LOST_TO_FOLLOW_UP = "LOST_TO_FOLLOW_UP"


class PayerType(str, Enum):
    MEDICAL = "MEDICAL"
    VISION = "VISION"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class AuthorizationCloseReason(str, Enum):
    PAYER_TERMINATED = "PAYER_TERMINATED"
    EPISODE_COMPLETE = "EPISODE_COMPLETE"
    PATIENT_DISCHARGED = "PATIENT_DISCHARGED"


class Credential(str, Enum):
    OPTOMETRIST = "OPTOMETRIST"
    CERTIFIED_VISION_THERAPIST = "CERTIFIED_VISION_THERAPIST"
    VISION_THERAPY_ASSISTANT = "VISION_THERAPY_ASSISTANT"


class EquipmentClass(str, Enum):
    STANDARD = "STANDARD"
    VECTOGRAM_SUITE = "VECTOGRAM_SUITE"
    COMPUTER_ORTHOPTICS = "COMPUTER_ORTHOPTICS"


class AssessmentType(str, Enum):
    EVALUATION = "EVALUATION"
    REASSESSMENT = "REASSESSMENT"


class AssessmentPurpose(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    PROGRESS = "PROGRESS"
    DISCHARGE_READINESS = "DISCHARGE_READINESS"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SIGNED = "SIGNED"


class MetricCode(str, Enum):
    NPC = "NPC"
    ACCOMMODATIVE_AMPLITUDE = "ACCOMMODATIVE_AMPLITUDE"
    VERGENCE_BASE_OUT = "VERGENCE_BASE_OUT"
    VISUAL_ACUITY = "VISUAL_ACUITY"
    SYMPTOM_SURVEY = "SYMPTOM_SURVEY"


class Eye(str, Enum):
    OD = "OD"
    OS = "OS"
    OU = "OU"


class ReferenceVariant(str, Enum):
    STANDARD = "STANDARD"
    FUNCTIONAL = "FUNCTIONAL"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    UNDER_REVISION = "UNDER_REVISION"
    COMPLETED = "COMPLETED"
    DISCHARGED = "DISCHARGED"


class ProgressState(str, Enum):
    ON_TRACK = "ON_TRACK"
    PLATEAU = "PLATEAU"
    REVISION_PENDING = "REVISION_PENDING"
    DISCHARGE_PENDING = "DISCHARGE_PENDING"


class DischargeCriteriaMode(str, Enum):
    METRIC = "METRIC"
    GOAL = "GOAL"


class SuspensionReason(str, Enum):
    RED_FLAG_REFERRAL = "RED_FLAG_REFERRAL"
    CLINICIAN_HOLD = "CLINICIAN_HOLD"


class PhaseStatus(str, Enum):
    LOCKED = "LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    MASTERED = "MASTERED"


class Modality(str, Enum):
    IN_OFFICE = "IN_OFFICE"
    HOME = "HOME"


class ProcedureCode(str, Enum):
    TIMED_THERAPEUTIC_ACTIVITY = "TIMED_THERAPEUTIC_ACTIVITY"
    FLAT_ORTHOPTIC_TRAINING = "FLAT_ORTHOPTIC_TRAINING"
    HOME_PRACTICE = "HOME_PRACTICE"
    EVALUATION_ENCOUNTER = "EVALUATION_ENCOUNTER"


class ScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    LOGGED = "LOGGED"
    ATTESTED = "ATTESTED"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    BILLABLE = "BILLABLE"
    NON_BILLABLE = "NON_BILLABLE"
    CLAIMED = "CLAIMED"
    SETTLED = "SETTLED"


class CancelReason(str, Enum):
    PATIENT_REQUEST = "PATIENT_REQUEST"
    CLINIC_REQUEST = "CLINIC_REQUEST"
    PLAN_SUSPENDED = "PLAN_SUSPENDED"
    PLAN_DISCHARGED = "PLAN_DISCHARGED"


class ItemClass(str, Enum):
    LOANABLE_SERIALIZED = "LOANABLE_SERIALIZED"
    CONSUMABLE_STOCK = "CONSUMABLE_STOCK"


class LoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CHECKED_OUT = "CHECKED_OUT"
    DISPENSED = "DISPENSED"
    RECALLED = "RECALLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ReturnedCondition(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class ServiceClass(str, Enum):
    THERAPY_SESSION = "THERAPY_SESSION"
    EVALUATION = "EVALUATION"


class AdjudicationVariant(str, Enum):
    MEDICAL = "MEDICAL"
    VISION = "VISION"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    DENIED = "DENIED"


class AdjudicationOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    DENIED = "DENIED"


class ReferralDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class ReferralUrgency(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ABANDONED = "ABANDONED"


class ResponseOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class OcclusionSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AgeBand(str, Enum):
    YOUNG = "YOUNG"
    SCHOOL = "SCHOOL"
    OLDER = "OLDER"


class OcclusionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TAPERED = "TAPERED"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# Every entity below carries id / created_at / updated_at / version except
# BinocularMeasurement, which the PRD declares carries id and created_at only.
# --------------------------------------------------------------------------


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    diagnosis_category: str
    guardian_name: Optional[str]
    clinical_status: str
    discharge_reason: Optional[str]
    discharged_at: Optional[str]
    discharged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    name: str
    payer_type: str
    allowed_amount_timed_unit: float
    allowed_amount_flat_session: float
    allowed_amount_evaluation: float
    coinsurance_rate: float
    frequency_limit_months: int
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict):
    id: str
    patient_id: str
    payer_id: str
    member_number: str
    status: str
    effective_start_date: str
    effective_end_date: str
    deductible_total: float
    deductible_met: float
    vision_allowance_total: float
    vision_allowance_used: float
    vision_allowance_remaining: float
    last_paid_service_date_therapy: Optional[str]
    last_paid_service_date_evaluation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    patient_id: str
    coverage_id: str
    auth_number: str
    visits_authorized: int
    visits_consumed: int
    visits_released: int
    visits_remaining: int
    window_start_date: str
    window_end_date: str
    status: str
    reauthorization_count: int
    last_reauthorized_at: Optional[str]
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict):
    id: str
    full_name: str
    credential: str
    credential_expires_at: str
    npi: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TherapyRoom(TypedDict):
    id: str
    name: str
    equipment_class: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    patient_id: str
    plan_id: Optional[str]
    performed_by_therapist_id: str
    signed_by_therapist_id: Optional[str]
    assessment_type: str
    purpose: str
    encounter_date: str
    patient_age_years: int
    status: str
    amendment_count: int
    signed_at: Optional[str]
    therapy_indicated: bool
    discharge_metric_met: bool
    composite_progress_score: Optional[float]
    symptom_improvement_pct: Optional[float]
    improvement_delta_points: Optional[float]
    plateau_flag: bool
    red_flag_present: bool
    created_at: str
    updated_at: str
    version: int


class BinocularMeasurement(TypedDict):
    """Immutable instrument reading: id and created_at only, no updated_at, no version."""

    id: str
    assessment_id: str
    metric_code: str
    eye: str
    npc_break_cm: Optional[float]
    npc_recovery_cm: Optional[float]
    amplitude_d: Optional[float]
    vergence_bo_break_pd: Optional[float]
    acuity_logmar: Optional[float]
    ciss_score: Optional[int]
    red_flag: bool
    reference_variant: Optional[str]
    expected_min_value: Optional[float]
    expected_band_high: Optional[float]
    within_reference_band: bool
    diagnostic_flag: bool
    created_at: str


class TherapyPlan(TypedDict):
    id: str
    patient_id: str
    source_assessment_id: str
    authorization_id: Optional[str]
    status: str
    progress_state: str
    discharge_criteria_mode: str
    current_phase_index: int
    prescribed_home_sessions_per_week: int
    previous_prescribed_home_sessions_per_week: Optional[int]
    prescription_changed_at: Optional[str]
    cumulative_therapy_minutes: float
    home_compliance_pct: float
    revision_count: int
    consecutive_low_delta_count: int
    suspension_reason: Optional[str]
    discharge_ready: bool
    baseline_npc_break_cm: Optional[float]
    baseline_amplitude_d: Optional[float]
    baseline_vergence_bo_break_pd: Optional[float]
    baseline_acuity_logmar: Optional[float]
    baseline_ciss_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PlanPhase(TypedDict):
    id: str
    plan_id: str
    sequence_index: int
    name: str
    required_mastery_count: int
    activities_mastered_count: int
    status: str
    started_at: Optional[str]
    mastered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TherapySession(TypedDict):
    id: str
    plan_id: str
    patient_id: str
    therapist_id: Optional[str]
    room_id: Optional[str]
    authorization_id: Optional[str]
    supervising_optometrist_id: Optional[str]
    modality: str
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    performed_at: Optional[str]
    timed_minutes: Optional[int]
    procedure_code: str
    billable_units: int
    charge_amount: float
    weighted_minutes: float
    schedule_status: str
    billing_status: str
    activities_mastered_delta: int
    cancel_reason: Optional[str]
    attested_at: Optional[str]
    attestation_statement: Optional[str]
    activity_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KitItem(TypedDict):
    id: str
    name: str
    item_class: str
    replacement_cost: float
    useful_life_months: int
    in_service_date: str
    initial_qty: int
    on_hand_qty: int
    on_loan_qty: int
    dispensed_qty: int
    retired_qty: int
    created_at: str
    updated_at: str
    version: int


class KitLoan(TypedDict):
    id: str
    kit_item_id: str
    patient_id: str
    plan_id: str
    quantity: int
    status: str
    checked_out_at: Optional[str]
    due_at: Optional[str]
    returned_at: Optional[str]
    returned_condition: Optional[str]
    damage_fee_amount: float
    recall_due_at: Optional[str]
    recalled_at: Optional[str]
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    patient_id: str
    coverage_id: str
    session_id: Optional[str]
    assessment_id: Optional[str]
    service_class: str
    service_date: str
    procedure_code: str
    units: int
    billed_amount: float
    allowed_amount: float
    contractual_adjustment_amount: float
    deductible_applied_amount: float
    coinsurance_amount: float
    plan_paid_amount: float
    patient_responsibility_amount: float
    denied_amount: float
    adjudication_variant: Optional[str]
    status: str
    appeal_count: int
    appeal_attempt_log_count: int
    last_appeal_attempt_at: Optional[str]
    correction_count: int
    submitted_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    plan_id: Optional[str]
    triggering_assessment_id: Optional[str]
    direction: str
    urgency: str
    referring_provider_name: str
    target_provider_name: str
    reason: str
    status: str
    sla_due_at: str
    responded_at: Optional[str]
    response_outcome: Optional[str]
    decline_reason: Optional[str]
    attempt_count: int
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class OcclusionPrescription(TypedDict):
    id: str
    patient_id: str
    source_assessment_id: str
    severity: str
    age_band: str
    prescribed_daily_hours: int
    current_daily_hours: int
    taper_step_count: int
    logged_days: int
    adherent_days: int
    adherence_pct: float
    baseline_acuity_logmar: float
    status: str
    created_at: str
    updated_at: str
    version: int
