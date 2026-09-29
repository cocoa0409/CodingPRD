"""Domain types for the L&D unit staffing / perinatal safety bundle API.

Status enums, role enum and entity TypedDicts. Every entity in this API
carries the common fields id / created_at / updated_at / version.
"""

from enum import Enum
from typing import Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CHARGE_NURSE = "ChargeNurse"
    BEDSIDE_NURSE = "BedsideNurse"
    OBSTETRICIAN_ATTENDING = "ObstetricianAttending"
    ANESTHESIA_LEAD = "AnesthesiaLead"
    PERINATAL_SAFETY_OFFICER = "PerinatalSafetyOfficer"
    PATIENT_ACCESS_COORDINATOR = "PatientAccessCoordinator"


ALL_ROLES = [r.value for r in UserRole]


class StaffingPosture(str, Enum):
    OPEN = "OPEN"
    RATIO_STRAINED = "RATIO_STRAINED"
    INDUCTION_FROZEN = "INDUCTION_FROZEN"
    DIVERT = "DIVERT"


class CesareanReadinessState(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"


class StaffRole(str, Enum):
    RN_LABOR_DELIVERY = "RN_LABOR_DELIVERY"
    OB_ATTENDING = "OB_ATTENDING"
    CERTIFIED_NURSE_MIDWIFE = "CERTIFIED_NURSE_MIDWIFE"
    ANESTHESIOLOGIST = "ANESTHESIOLOGIST"
    SURGICAL_TECH = "SURGICAL_TECH"
    NEONATAL_RESUSCITATOR = "NEONATAL_RESUSCITATOR"


class CertLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    EXPIRED = "EXPIRED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class DrillCurrencyState(str, Enum):
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"


class RoleSlot(str, Enum):
    CHARGE = "CHARGE"
    BEDSIDE = "BEDSIDE"
    ONE_TO_ONE_FLOAT = "ONE_TO_ONE_FLOAT"
    OR_STANDBY = "OR_STANDBY"
    TRIAGE = "TRIAGE"


class ShiftAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELIEVED = "RELIEVED"
    CANCELLED = "CANCELLED"


class BedType(str, Enum):
    LDR = "LDR"
    OR = "OR"
    TRIAGE = "TRIAGE"
    POSTPARTUM = "POSTPARTUM"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    TURNOVER = "TURNOVER"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class LaborPhase(str, Enum):
    ANTEPARTUM = "ANTEPARTUM"
    LATENT = "LATENT"
    ACTIVE_FIRST_STAGE = "ACTIVE_FIRST_STAGE"
    SECOND_STAGE = "SECOND_STAGE"
    THIRD_STAGE_DELIVERED = "THIRD_STAGE_DELIVERED"
    POSTPARTUM_RECOVERY = "POSTPARTUM_RECOVERY"
    DISCHARGED = "DISCHARGED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class StaffingState(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    RATIO_COVERED = "RATIO_COVERED"
    ONE_TO_ONE_COVERED = "ONE_TO_ONE_COVERED"
    COVERAGE_BREACH = "COVERAGE_BREACH"
    RELEASED = "RELEASED"


class AcuityTier(str, Enum):
    TIER_I = "TIER_I"
    TIER_II = "TIER_II"
    TIER_III = "TIER_III"
    TIER_IV = "TIER_IV"


class Presentation(str, Enum):
    VERTEX = "VERTEX"
    BREECH = "BREECH"
    OTHER = "OTHER"


class DeliveryMode(str, Enum):
    SPONTANEOUS_VAGINAL = "SPONTANEOUS_VAGINAL"
    OPERATIVE_VAGINAL = "OPERATIVE_VAGINAL"
    CESAREAN_PRIMARY = "CESAREAN_PRIMARY"
    CESAREAN_REPEAT = "CESAREAN_REPEAT"


class CoverageMode(str, Enum):
    RATIO_SHARED = "RATIO_SHARED"
    ONE_TO_ONE = "ONE_TO_ONE"


class CareAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class IndicationCode(str, Enum):
    PREECLAMPSIA = "PREECLAMPSIA"
    POST_DATES_41W = "POST_DATES_41W"
    FGR = "FGR"
    PROM = "PROM"
    GDM_CONTROLLED = "GDM_CONTROLLED"
    ELECTIVE_NO_INDICATION = "ELECTIVE_NO_INDICATION"


class PriorityClass(str, Enum):
    MEDICALLY_INDICATED = "MEDICALLY_INDICATED"
    ELECTIVE_39_WEEK = "ELECTIVE_39_WEEK"
    PATIENT_REQUEST = "PATIENT_REQUEST"


class InductionBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CAPACITY_HELD = "CAPACITY_HELD"
    CONFIRMED = "CONFIRMED"
    ADMITTED = "ADMITTED"
    BUMPED = "BUMPED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class BundleType(str, Enum):
    OBSTETRIC_HEMORRHAGE = "OBSTETRIC_HEMORRHAGE"
    SEVERE_HYPERTENSION = "SEVERE_HYPERTENSION"


class ActivationTrigger(str, Enum):
    QBL_THRESHOLD = "QBL_THRESHOLD"
    BP_THRESHOLD = "BP_THRESHOLD"
    CLINICIAN_JUDGMENT = "CLINICIAN_JUDGMENT"


class BundleActivationStatus(str, Enum):
    ACTIVATED = "ACTIVATED"
    STAGE_1_IN_PROGRESS = "STAGE_1_IN_PROGRESS"
    STAGE_2_ESCALATED = "STAGE_2_ESCALATED"
    STAGE_3_MASSIVE_TRANSFUSION = "STAGE_3_MASSIVE_TRANSFUSION"
    CONTROLLED = "CONTROLLED"
    DEBRIEF_PENDING = "DEBRIEF_PENDING"
    CLOSED = "CLOSED"
    RESCINDED = "RESCINDED"


class StepCode(str, Enum):
    QBL_MEASURE = "QBL_MEASURE"
    UTEROTONIC_GIVEN = "UTEROTONIC_GIVEN"
    TYPE_AND_SCREEN = "TYPE_AND_SCREEN"
    MTP_ACTIVATED = "MTP_ACTIVATED"
    ANTIHYPERTENSIVE_GIVEN = "ANTIHYPERTENSIVE_GIVEN"
    MAGNESIUM_LOADED = "MAGNESIUM_LOADED"
    REPEAT_BP = "REPEAT_BP"
    OB_AT_BEDSIDE = "OB_AT_BEDSIDE"


class ChecklistItemStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    LATE_COMPLETED = "LATE_COMPLETED"
    MISSED = "MISSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FetalCategory(str, Enum):
    CATEGORY_I = "CATEGORY_I"
    CATEGORY_II = "CATEGORY_II"
    CATEGORY_III = "CATEGORY_III"


class Variability(str, Enum):
    ABSENT = "ABSENT"
    MINIMAL = "MINIMAL"
    MODERATE = "MODERATE"
    MARKED = "MARKED"


class EscalationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    ESCALATION_DUE = "ESCALATION_DUE"
    TIER_1_NOTIFIED = "TIER_1_NOTIFIED"
    TIER_2_NOTIFIED = "TIER_2_NOTIFIED"
    TIER_3_ACTIVATED = "TIER_3_ACTIVATED"
    REASSESSMENT_PENDING = "REASSESSMENT_PENDING"
    RESOLVED = "RESOLVED"
    TIMED_OUT_BREACH = "TIMED_OUT_BREACH"


class UrgencyClass(str, Enum):
    CATEGORY_1_CRASH = "CATEGORY_1_CRASH"
    CATEGORY_2_URGENT = "CATEGORY_2_URGENT"


class CesareanEventStatus(str, Enum):
    DECISION_DECLARED = "DECISION_DECLARED"
    TEAM_MOBILIZED = "TEAM_MOBILIZED"
    INCISION_RECORDED = "INCISION_RECORDED"
    DELIVERED = "DELIVERED"
    REVIEW_PENDING = "REVIEW_PENDING"
    CLOSED = "CLOSED"
    ABORTED_TO_VAGINAL = "ABORTED_TO_VAGINAL"


class DrillType(str, Enum):
    DECISION_TO_INCISION = "DECISION_TO_INCISION"
    HEMORRHAGE_STAGE_2 = "HEMORRHAGE_STAGE_2"
    ECLAMPSIA = "ECLAMPSIA"


class DrillStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DOCUMENTED = "DOCUMENTED"
    VALIDATED = "VALIDATED"
    INVALIDATED = "INVALIDATED"
    ABANDONED = "ABANDONED"


class ComplicationCode(str, Enum):
    UNEXPECTED_NICU_TERM = "UNEXPECTED_NICU_TERM"
    HIE_SUSPECTED = "HIE_SUSPECTED"
    APGAR5_UNDER_7 = "APGAR5_UNDER_7"
    BIRTH_INJURY = "BIRTH_INJURY"
    UNEXPECTED_TRANSFER = "UNEXPECTED_TRANSFER"


class ContributingFactorCode(str, Enum):
    STAFFING_RATIO = "STAFFING_RATIO"
    MONITORING_INTERPRETATION = "MONITORING_INTERPRETATION"
    BUNDLE_DELAY = "BUNDLE_DELAY"
    COMMUNICATION = "COMMUNICATION"
    EQUIPMENT = "EQUIPMENT"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    DEBRIEF_SCHEDULED = "DEBRIEF_SCHEDULED"
    FINDINGS_SUBMITTED = "FINDINGS_SUBMITTED"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    CLOSED = "CLOSED"


class CredentialType(str, Enum):
    PARTNER = "PARTNER"
    DOULA_CERTIFIED = "DOULA_CERTIFIED"
    STUDENT_OBSERVER = "STUDENT_OBSERVER"
    INTERPRETER = "INTERPRETER"


class SupportPassStatus(str, Enum):
    ISSUED = "ISSUED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class PostureReasonCode(str, Enum):
    DIVERT_DEFICIT = "DIVERT_DEFICIT"
    NO_AVAILABLE_LDR_BED = "NO_AVAILABLE_LDR_BED"
    STAGE_3_BUNDLE = "STAGE_3_BUNDLE"
    FREEZE_DEFICIT = "FREEZE_DEFICIT"
    ESCALATION_BREACH = "ESCALATION_BREACH"
    BUNDLE_BREACH = "BUNDLE_BREACH"
    READINESS_NOT_READY = "READINESS_NOT_READY"
    STAGE_2_WITH_DEFICIT = "STAGE_2_WITH_DEFICIT"
    DEFICIT_POSITIVE = "DEFICIT_POSITIVE"
    BREACHED_ENCOUNTER = "BREACHED_ENCOUNTER"
    NONE = "NONE"


class ObstetricUnit(TypedDict, total=False):
    id: str
    unit_name: str
    licensed_ldr_beds: int
    licensed_or_rooms: int
    max_daily_induction_bed_minutes: int
    staffing_posture: str
    coverage_deficit_units: float
    cesarean_readiness_state: str
    escalation_breach_count: int
    bundle_breach_count: int
    turnover_buffer_minutes: int
    committed_bed_minutes_by_day: Dict[str, int]
    held_bed_minutes_by_day: Dict[str, int]
    last_capacity_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    unit_id: str
    full_name: str
    staff_role: str
    fetal_monitoring_cert_level: str
    credential_expires_at: str
    or_circulating_qualified: bool
    employment_status: str
    last_validated_drill_at: Optional[str]
    drill_currency_state: str
    capacity_units: float
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    unit_id: str
    staff_id: str
    role_slot: str
    shift_start_utc: str
    shift_end_utc: str
    status: str
    capacity_units_effective: Optional[float]
    assigned_acuity_load_units: float
    relieved_by_shift_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict, total=False):
    id: str
    unit_id: str
    bed_label: str
    bed_type: str
    status: str
    current_encounter_id: Optional[str]
    held_booking_id: Optional[str]
    turnover_clear_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaborEncounter(TypedDict, total=False):
    id: str
    unit_id: str
    bed_id: Optional[str]
    source_booking_id: Optional[str]
    patient_record_code: str
    labor_phase: str
    staffing_state: str
    parity: int
    prior_cesarean: bool
    gestational_age_weeks: int
    fetus_count: int
    presentation: str
    is_ntsv: bool
    acuity_tier: str
    one_to_one_required: bool
    required_coverage_units: float
    assigned_coverage_units: float
    magnesium_infusion_active: bool
    delivery_mode: Optional[str]
    episiotomy_performed: bool
    admitted_at: str
    delivery_recorded_at: Optional[str]
    review_required: bool
    created_at: str
    updated_at: str
    version: int


class CareAssignment(TypedDict, total=False):
    id: str
    encounter_id: str
    shift_assignment_id: str
    staff_id: str
    coverage_mode: str
    acuity_units_consumed: float
    status: str
    released_at: Optional[str]
    superseded_by_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InductionBooking(TypedDict, total=False):
    id: str
    unit_id: str
    bed_id: Optional[str]
    encounter_id: Optional[str]
    patient_record_code: str
    gestational_age_weeks: int
    indication_code: str
    priority_class: str
    requested_start_utc: str
    expected_labor_minutes: int
    projected_occupancy_minutes: Optional[int]
    hold_expires_at: Optional[str]
    status: str
    bump_count: int
    created_at: str
    updated_at: str
    version: int


class SafetyBundleActivation(TypedDict, total=False):
    id: str
    encounter_id: str
    unit_id: str
    bundle_type: str
    activation_trigger: str
    quantitative_blood_loss_ml: Optional[int]
    systolic_mmhg: Optional[int]
    diastolic_mmhg: Optional[int]
    activated_at: str
    status: str
    highest_stage_reached: int
    on_time_step_count: int
    late_step_count: int
    missed_step_count: int
    timeliness_score: Optional[float]
    sequence_adjusted_score: Optional[float]
    rescind_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BundleChecklistItem(TypedDict, total=False):
    id: str
    activation_id: str
    step_code: str
    step_sequence: int
    stage_gate: int
    required_within_minutes: int
    due_at_activation_anchored: str
    due_at_sequence_anchored: Optional[str]
    status: str
    completed_at: Optional[str]
    performed_by_staff_id: Optional[str]
    minutes_from_activation: Optional[float]
    created_at: str
    updated_at: str
    version: int


class FetalMonitoringAssessment(TypedDict, total=False):
    id: str
    encounter_id: str
    interpreted_by_staff_id: str
    supersedes_assessment_id: Optional[str]
    assessed_at: str
    category: str
    baseline_rate_bpm: int
    variability: str
    recurrent_decelerations: bool
    escalation_status: str
    escalation_tier_high_water: int
    escalation_due_at: Optional[str]
    next_tier_due_at: Optional[str]
    reassessment_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyCesareanEvent(TypedDict, total=False):
    id: str
    encounter_id: str
    or_bed_id: Optional[str]
    triggering_assessment_id: Optional[str]
    triggering_activation_id: Optional[str]
    urgency_class: str
    decision_at: str
    incision_at: Optional[str]
    delivery_at: Optional[str]
    decision_to_incision_minutes: Optional[int]
    met_target: Optional[bool]
    mobilized_staff_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CesareanReadinessDrill(TypedDict, total=False):
    id: str
    unit_id: str
    drill_type: str
    scheduled_for_utc: str
    participant_staff_ids: List[str]
    decision_at: Optional[str]
    incision_at: Optional[str]
    measured_d2i_minutes: Optional[int]
    status: str
    validated_at: Optional[str]
    validated_by_user_id: Optional[str]
    documented_by_staff_id: Optional[str]
    expires_at: Optional[str]
    invalidation_reason: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class NewbornComplicationReview(TypedDict, total=False):
    id: str
    encounter_id: str
    complication_code: str
    facilitator_staff_id: str
    opened_at: str
    debrief_due_at: str
    debrief_scheduled_for_utc: Optional[str]
    debrief_held_at: Optional[str]
    findings_summary: Optional[str]
    contributing_factor_codes: List[str]
    status: str
    rework_count: int
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportPersonPass(TypedDict, total=False):
    id: str
    encounter_id: str
    person_name: str
    credential_type: str
    doula_certification_expires_at: Optional[str]
    or_credentialed: bool
    status: str
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    valid_until: str
    reentry_count: int
    created_at: str
    updated_at: str
    version: int


class QualityMeasureSnapshot(TypedDict, total=False):
    id: str
    unit_id: str
    period_start_utc: str
    period_end_utc: str
    attribution_basis: str
    ntsv_cesarean_numerator: int
    ntsv_cesarean_denominator: int
    ntsv_cesarean_rate_pct: Optional[float]
    episiotomy_numerator: int
    episiotomy_denominator: int
    episiotomy_rate_pct: Optional[float]
    shadow_ntsv_rate_pct: Optional[float]
    composite_quality_index: Optional[float]
    status: str
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    superseded_by_snapshot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
