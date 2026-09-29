"""Domain types for the Neonatal Network API: status enums, code enums, role enum
and one TypedDict per resource described in the PRD.

Every enum value below is spelled exactly as the PRD spells it.
"""

from enum import Enum
from typing import List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    UNIT_DIRECTOR = "UnitDirector"
    INTAKE_NEONATOLOGIST = "IntakeNeonatologist"
    REFERRING_CLINICIAN = "ReferringClinician"
    TRANSPORT_COORDINATOR = "TransportCoordinator"
    BEDSIDE_NURSE = "BedsideNurse"
    FOLLOWUP_COORDINATOR = "FollowUpCoordinator"


# ---------------------------------------------------------------------------
# Level of care ladder (PRD §2.7)
# ---------------------------------------------------------------------------


class CareLevel(str, Enum):
    LEVEL_I = "LEVEL_I"
    LEVEL_II = "LEVEL_II"
    LEVEL_III = "LEVEL_III"
    LEVEL_IV = "LEVEL_IV"


LEVEL_RANKS = {
    "LEVEL_I": 1,
    "LEVEL_II": 2,
    "LEVEL_III": 3,
    "LEVEL_IV": 4,
}


# ---------------------------------------------------------------------------
# NicuUnit
# ---------------------------------------------------------------------------


class HospitalType(str, Enum):
    REGIONAL_CENTER = "REGIONAL_CENTER"
    COMMUNITY = "COMMUNITY"


class DesignationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    DESIGNATED = "DESIGNATED"
    CONDITIONAL = "CONDITIONAL"
    SUSPENDED = "SUSPENDED"


class CensusPosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    CLOSED = "CLOSED"


class QualityFlag(str, Enum):
    WITHIN_BENCHMARK = "WITHIN_BENCHMARK"
    ABOVE_BENCHMARK = "ABOVE_BENCHMARK"


class NicuUnit(TypedDict):
    id: str
    name: str
    hospital_type: str
    designated_level: str
    designation_status: str
    capability_level: str
    effective_level: str
    staffing_compliant: bool
    equipment_compliant: bool
    staffed_bed_target: int
    escalation_bed_count: int
    occupied_bed_count: int
    held_bed_count: int
    available_bed_count: int
    census_posture: str
    required_nurse_count: int
    transport_capable: bool
    annual_admission_volume: int
    followup_clinic_daily_capacity: int
    quality_flag: str
    deferral_queue_depth: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# DesignationStandard — immutable, so it carries only id + created_at (PRD §2.4)
# ---------------------------------------------------------------------------


class DesignationStandard(TypedDict):
    id: str
    level: str
    required_credential_codes: List[str]
    required_equipment_codes: List[str]
    nurse_patient_ratio_denominator: float
    min_annual_volume: int
    transport_capability_required: bool
    min_compliance_score: float
    conditional_floor_score: float
    created_at: str


# ---------------------------------------------------------------------------
# StaffCredential
# ---------------------------------------------------------------------------


class CredentialCode(str, Enum):
    NEO_BOARD = "NEO_BOARD"
    NNP = "NNP"
    RN_NICU_CORE = "RN_NICU_CORE"
    RT_NEO = "RT_NEO"
    TRANSPORT_RN = "TRANSPORT_RN"
    LACTATION_IBCLC = "LACTATION_IBCLC"
    DEV_CARE_CERT = "DEV_CARE_CERT"


class CredentialStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class StaffCredential(TypedDict):
    id: str
    unit_id: str
    credential_code: str
    holder_reference: str
    fte: float
    expires_on: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# EquipmentAsset
# ---------------------------------------------------------------------------


class EquipmentCode(str, Enum):
    CONVENTIONAL_VENT = "CONVENTIONAL_VENT"
    HFOV = "HFOV"
    INHALED_NO = "INHALED_NO"
    THERAPEUTIC_HYPOTHERMIA = "THERAPEUTIC_HYPOTHERMIA"
    TRANSPORT_ISOLETTE = "TRANSPORT_ISOLETTE"
    ECMO_CIRCUIT = "ECMO_CIRCUIT"


class EquipmentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    SERVICE_DUE = "SERVICE_DUE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class OutOfServiceReason(str, Enum):
    BIOMED_FAULT = "BIOMED_FAULT"
    RECALL = "RECALL"
    CONTAMINATION = "CONTAMINATION"
    AWAITING_PARTS = "AWAITING_PARTS"
    SCHEDULED_SERVICE = "SCHEDULED_SERVICE"


class EquipmentAsset(TypedDict):
    id: str
    unit_id: str
    equipment_code: str
    asset_tag: str
    last_service_at: str
    service_interval_days: int
    next_service_due_at: str
    out_of_service_at: Optional[str]
    out_of_service_reason: Optional[str]
    status: str
    decontamination_ready_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# DesignationReview
# ---------------------------------------------------------------------------


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    VERIFIED = "VERIFIED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"


class DenialBasis(str, Enum):
    ROUNDS_EXHAUSTED = "ROUNDS_EXHAUSTED"
    SCORE_BELOW_FLOOR = "SCORE_BELOW_FLOOR"


class DesignationReview(TypedDict):
    id: str
    unit_id: str
    requested_level: str
    assigned_nurse_count: int
    status: str
    submission_round: int
    assessment_at: Optional[str]
    submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    required_nurse_count: int
    staffing_subscore: float
    equipment_subscore: float
    volume_subscore: float
    compliance_score: float
    outcome_level: Optional[str]
    return_reason: Optional[str]
    denial_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------


class ReferralKind(str, Enum):
    INBOUND_NEONATAL = "INBOUND_NEONATAL"
    MATERNAL_ANTENATAL = "MATERNAL_ANTENATAL"
    BACK_TRANSFER = "BACK_TRANSFER"


class SupportModality(str, Enum):
    ROOM_AIR = "ROOM_AIR"
    CPAP = "CPAP"
    CONVENTIONAL_VENT = "CONVENTIONAL_VENT"
    HFOV = "HFOV"
    INHALED_NO = "INHALED_NO"
    ECMO_CONSULT = "ECMO_CONSULT"


class Diagnosis(str, Enum):
    RDS_SEVERE = "RDS_SEVERE"
    HIE_MODERATE = "HIE_MODERATE"
    PROM = "PROM"
    CHD_DUCTAL = "CHD_DUCTAL"
    SURGICAL_NEC = "SURGICAL_NEC"


class LevelBasis(str, Enum):
    CURRENT_SUPPORT = "CURRENT_SUPPORT"
    ANTICIPATED_NEED = "ANTICIPATED_NEED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    INFO_REQUESTED = "INFO_REQUESTED"
    ACCEPTED = "ACCEPTED"
    DEFERRED = "DEFERRED"
    DECLINED = "DECLINED"
    DIVERTED = "DIVERTED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class DecisionReason(str, Enum):
    NO_CAPABILITY = "NO_CAPABILITY"
    CLINICAL_DECLINE = "CLINICAL_DECLINE"
    FAMILY_CHOICE = "FAMILY_CHOICE"
    NO_BED = "NO_BED"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    CAPABILITY_LOST = "CAPABILITY_LOST"
    INFO_ROUNDS_EXHAUSTED = "INFO_ROUNDS_EXHAUSTED"
    TRANSPORT_ABORTED = "TRANSPORT_ABORTED"


class Referral(TypedDict):
    id: str
    referring_unit_id: str
    receiving_unit_id: str
    source_admission_id: Optional[str]
    superseded_by_referral_id: Optional[str]
    referral_kind: str
    case_reference: str
    gestational_age_weeks: float
    birth_weight_grams: int
    weight_basis_grams: int
    support_modality: str
    diagnoses: List[str]
    planned_surgery: bool
    current_support_level: str
    anticipated_need_level: str
    level_basis: str
    required_level: str
    maternal_transfer_preferred: bool
    triage_priority: float
    status: str
    info_request_rounds: int
    requested_items: Optional[str]
    decision_reason: Optional[str]
    reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# BedReservation
# ---------------------------------------------------------------------------


class BedClass(str, Enum):
    STAFFED = "STAFFED"
    ESCALATION = "ESCALATION"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class ReleasedReason(str, Enum):
    ADMITTED = "ADMITTED"
    REVOKED = "REVOKED"
    REFERRAL_WITHDRAWN = "REFERRAL_WITHDRAWN"
    CAPABILITY_LOST = "CAPABILITY_LOST"
    TRANSPORT_ABORTED = "TRANSPORT_ABORTED"
    HOLD_EXPIRED = "HOLD_EXPIRED"


class BedReservation(TypedDict):
    id: str
    unit_id: str
    referral_id: str
    bed_class: str
    held_at: str
    expires_at: str
    status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# TransportRun
# ---------------------------------------------------------------------------


class TransportMode(str, Enum):
    GROUND = "GROUND"
    ROTOR_WING = "ROTOR_WING"
    FIXED_WING = "FIXED_WING"


class RunStatus(str, Enum):
    ACTIVATED = "ACTIVATED"
    GROUND_ROLLING = "GROUND_ROLLING"
    AIR_LAUNCHED = "AIR_LAUNCHED"
    ON_SCENE = "ON_SCENE"
    STABILIZING = "STABILIZING"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    ABORTED = "ABORTED"


class AbortReason(str, Enum):
    WEATHER = "WEATHER"
    CREW_UNAVAILABLE = "CREW_UNAVAILABLE"
    PATIENT_DEMISE = "PATIENT_DEMISE"
    CAPABILITY_LOST = "CAPABILITY_LOST"
    HOLD_EXPIRED = "HOLD_EXPIRED"


class TransportRun(TypedDict):
    id: str
    reservation_id: str
    receiving_unit_id: str
    isolette_asset_id: str
    mode: str
    crew_composition: List[str]
    depart_at: str
    planned_return_at: str
    weather_minimums_met: bool
    status: str
    decontamination_minutes: int
    temp_c: Optional[float]
    glucose_mg_dl: Optional[float]
    mean_bp_mmhg: Optional[float]
    spo2_pct: Optional[float]
    stabilization_score: Optional[float]
    stabilization_bundle_complete: bool
    arrived_at: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------


class CareStatus(str, Enum):
    ADMITTED = "ADMITTED"
    STABILIZED = "STABILIZED"
    BACK_TRANSFER_READY = "BACK_TRANSFER_READY"
    BACK_TRANSFER_REQUIRED = "BACK_TRANSFER_REQUIRED"
    TRANSFERRED = "TRANSFERRED"
    DISCHARGED = "DISCHARGED"
    DECEASED = "DECEASED"


class InfectionStatus(str, Enum):
    SURVEILLANCE_CLEAR = "SURVEILLANCE_CLEAR"
    SUSPECTED = "SUSPECTED"
    CONFIRMED_CLABSI = "CONFIRMED_CLABSI"
    RESOLVED = "RESOLVED"


class InfectionEvent(str, Enum):
    SUSPECT = "SUSPECT"
    CONFIRM_CLABSI = "CONFIRM_CLABSI"
    RESOLVE = "RESOLVE"


class DischargeDisposition(str, Enum):
    HOME = "HOME"
    DECEASED = "DECEASED"
    BACK_TRANSFERRED = "BACK_TRANSFERRED"


class Admission(TypedDict):
    id: str
    unit_id: str
    referral_id: str
    transport_run_id: Optional[str]
    back_transfer_source_admission_id: Optional[str]
    gestational_age_weeks: float
    birth_weight_grams: int
    current_weight_grams: int
    support_modality: str
    current_care_level: str
    care_status: str
    infection_status: str
    infection_confirmed_at: Optional[str]
    patient_days: int
    central_line_days: int
    ventilator_days: int
    developmental_round_count: int
    kangaroo_care_sessions: int
    family_presence_minutes: int
    cluster_care_compliant_count: int
    light_cycling_compliant_count: int
    developmental_bundle_score: float
    milk_administered_ml: float
    high_risk_graduate: bool
    back_transfer_attestation_note: Optional[str]
    discharged_at: Optional[str]
    discharge_disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# MilkBatch
# ---------------------------------------------------------------------------


class DonorType(str, Enum):
    MOTHERS_OWN = "MOTHERS_OWN"
    DONOR_PASTEURIZED = "DONOR_PASTEURIZED"


class MilkBatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    PARTIALLY_ADMINISTERED = "PARTIALLY_ADMINISTERED"
    ADMINISTERED = "ADMINISTERED"
    QUARANTINED = "QUARANTINED"
    DISCARDED = "DISCARDED"


class DiscardReason(str, Enum):
    EXPIRED = "EXPIRED"
    LABEL_MISMATCH = "LABEL_MISMATCH"
    QUARANTINE_DISPOSAL = "QUARANTINE_DISPOSAL"
    FAMILY_REQUEST = "FAMILY_REQUEST"


class MilkBatch(TypedDict):
    id: str
    admission_id: str
    donor_type: str
    volume_ml: float
    expressed_at: str
    expires_at: str
    label_code: str
    received_by_user_id: str
    verified_by_user_id: Optional[str]
    administered_ml: float
    discarded_ml: float
    remaining_ml: float
    status: str
    pre_quarantine_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# SurgeEscalation
# ---------------------------------------------------------------------------


class EscalationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    STOOD_DOWN = "STOOD_DOWN"


class EscalationTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class SurgeEscalation(TypedDict):
    id: str
    unit_id: str
    requested_beds: int
    effective_from: str
    effective_to: str
    census_ratio_at_request: Optional[float]
    escalation_tier: Optional[str]
    staffing_waiver_ratio: Optional[float]
    authorized_beds: Optional[int]
    status: str
    authorized_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# SurveillanceReport
# ---------------------------------------------------------------------------


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class VariantApplied(str, Enum):
    CRUDE = "CRUDE"
    DEVICE_ADJUSTED = "DEVICE_ADJUSTED"


class DataCompletenessFlag(str, Enum):
    COMPLETE = "COMPLETE"
    DENOMINATOR_MISSING = "DENOMINATOR_MISSING"


class SurveillanceReport(TypedDict):
    id: str
    unit_id: str
    period_start: str
    period_end: str
    reported_patient_days: int
    reported_central_line_days: int
    clabsi_count: int
    mortality_count: int
    cohort_size: int
    birth_weight_risk_weight: float
    crude_clabsi_rate: float
    device_adjusted_clabsi_rate: float
    variant_applied: str
    data_completeness_flag: str
    network_benchmark_flag: str
    status: str
    submitted_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# FollowUpEnrollment
# ---------------------------------------------------------------------------


class EligibilityBasis(str, Enum):
    BW_UNDER_1500 = "BW_UNDER_1500"
    GA_UNDER_32 = "GA_UNDER_32"
    HIE_COOLED = "HIE_COOLED"
    SURGICAL_NEC = "SURGICAL_NEC"
    VENT_OVER_7D = "VENT_OVER_7D"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class RiskTier(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    LOST_TO_FOLLOWUP = "LOST_TO_FOLLOWUP"


class FollowUpEnrollment(TypedDict):
    id: str
    admission_id: str
    clinic_unit_id: str
    target_appointment_date: str
    confirmed_appointment_date: Optional[str]
    appointment_window_start: str
    appointment_window_end: str
    eligibility_basis: str
    risk_tier: str
    status: str
    attendance_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
