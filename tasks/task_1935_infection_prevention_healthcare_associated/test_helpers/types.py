"""Domain types: entity TypedDicts, status enums, role enum for the
infection-prevention surveillance API (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INFECTION_PREVENTIONIST = "InfectionPreventionist"
    INFECTION_CONTROL_DIRECTOR = "InfectionControlDirector"
    UNIT_NURSE_MANAGER = "UnitNurseManager"
    EMPLOYEE_HEALTH_NURSE = "EmployeeHealthNurse"


class UnitType(str, Enum):
    ICU = "ICU"
    WARD = "WARD"
    STEP_DOWN = "STEP_DOWN"
    OR = "OR"


class SurveillancePosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    OUTBREAK = "OUTBREAK"


class PatientStatus(str, Enum):
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"


class DeviceType(str, Enum):
    CENTRAL_LINE = "CENTRAL_LINE"
    URINARY_CATHETER = "URINARY_CATHETER"
    VENTILATOR = "VENTILATOR"


class DeviceEpisodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class WoundClass(str, Enum):
    CLEAN = "CLEAN"
    CLEAN_CONTAMINATED = "CLEAN_CONTAMINATED"
    CONTAMINATED = "CONTAMINATED"
    DIRTY = "DIRTY"


class CaseType(str, Enum):
    CLABSI = "CLABSI"
    CAUTI = "CAUTI"
    SSI = "SSI"
    OTHER_BSI = "OTHER_BSI"


class InfectionCaseStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADJUDICATED_HAI = "ADJUDICATED_HAI"
    RULED_OUT = "RULED_OUT"
    REOPENED = "REOPENED"


class SsiDepth(str, Enum):
    SURFACE = "SURFACE"
    DEEP = "DEEP"
    ORGAN_SPACE = "ORGAN_SPACE"


class DeviceDayCountStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"


class MonthlySummaryStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"


class SirFlag(str, Enum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    NOT_CALCULATED = "NOT_CALCULATED"


class OutbreakStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    CONFIRMED = "CONFIRMED"
    RULED_OUT = "RULED_OUT"
    CLOSED = "CLOSED"


class OutbreakOrigin(str, Enum):
    AUTO_THRESHOLD = "AUTO_THRESHOLD"
    MANUAL = "MANUAL"


class PrecautionType(str, Enum):
    CONTACT = "CONTACT"
    DROPLET = "DROPLET"
    AIRBORNE = "AIRBORNE"


class IsolationOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ComplianceStatus(str, Enum):
    NOT_AUDITED = "NOT_AUDITED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class AuditOutcome(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class OpportunityType(str, Enum):
    BEFORE_PATIENT_CONTACT = "BEFORE_PATIENT_CONTACT"
    AFTER_PATIENT_CONTACT = "AFTER_PATIENT_CONTACT"
    ASEPTIC_TASK = "ASEPTIC_TASK"
    BODY_FLUID_RISK = "BODY_FLUID_RISK"
    AFTER_SURROUNDINGS = "AFTER_SURROUNDINGS"


class ObservationAction(str, Enum):
    COMPLIANT = "COMPLIANT"
    MISSED = "MISSED"


class ExposureType(str, Enum):
    PERCUTANEOUS = "PERCUTANEOUS"
    MUCOUS_MEMBRANE = "MUCOUS_MEMBRANE"
    SKIN = "SKIN"


class Serostatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class ExposureStage(str, Enum):
    BASELINE = "BASELINE"
    WEEK_6 = "WEEK_6"
    WEEK_12 = "WEEK_12"
    WEEK_24 = "WEEK_24"


class ExposureStatus(str, Enum):
    REPORTED = "REPORTED"
    SOURCE_EVALUATED = "SOURCE_EVALUATED"
    BASELINE_COMPLETE = "BASELINE_COMPLETE"
    FOLLOWUP_IN_PROGRESS = "FOLLOWUP_IN_PROGRESS"
    COMPLETED = "COMPLETED"
    LOST_TO_FOLLOWUP = "LOST_TO_FOLLOWUP"


class CapSourceType(str, Enum):
    OUTBREAK = "OUTBREAK"
    ISOLATION_AUDIT = "ISOLATION_AUDIT"
    HAND_HYGIENE = "HAND_HYGIENE"
    SIR_HIGH = "SIR_HIGH"


class CapStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    ESCALATED = "ESCALATED"


# --- Entity TypedDicts (every resource carries id/created_at/updated_at/version,
# per PRD §2.4) ---


class Facility(TypedDict, total=False):
    id: str
    name: str
    nhsn_org_id: str
    clabsi_baseline_per_1000: float
    cauti_baseline_per_1000: float
    ssi_baseline_per_procedure: float
    sir_high_threshold: float
    hh_min_opportunities: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    facility_id: str
    name: str
    unit_type: str
    nhsn_location_code: str
    surveillance_posture: str
    created_at: str
    updated_at: str
    version: int


class UnitStay(TypedDict, total=False):
    unit_id: str
    arrived_at: str
    departed_at: Optional[str]


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    admitted_at: str
    unit_id: str
    current_unit_id: Optional[str]
    unit_stays: List[UnitStay]
    discharged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employee_code: str
    role_title: str
    home_unit_id: str
    created_at: str
    updated_at: str
    version: int


class DeviceEpisode(TypedDict, total=False):
    id: str
    patient_id: str
    unit_id: str
    device_type: str
    placed_at: str
    removed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurgicalProcedure(TypedDict, total=False):
    id: str
    patient_id: str
    unit_id: str
    procedure_code: str
    performed_at: str
    duration_minutes: int
    asa_score: int
    wound_class: str
    implant: bool
    created_at: str
    updated_at: str
    version: int


class InfectionCase(TypedDict, total=False):
    id: str
    patient_id: str
    unit_id: str
    case_type: str
    suspected_organism: str
    first_positive_specimen_at: str
    surgical_procedure_id: Optional[str]
    linked_device_episode_id: Optional[str]
    infection_window_start: str
    infection_window_end: str
    date_of_event: Optional[str]
    is_hai: Optional[bool]
    rit_blocked_until: Optional[str]
    ssi_depth: Optional[str]
    status: str
    adjudicated_by_user_id: Optional[str]
    adjudication_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceDayCount(TypedDict, total=False):
    id: str
    unit_id: str
    count_date: str
    central_line_days: int
    urinary_catheter_days: int
    ventilator_days: int
    patient_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlySummary(TypedDict, total=False):
    id: str
    unit_id: str
    month: str
    central_line_days: int
    urinary_catheter_days: int
    ventilator_days: int
    patient_days_total: int
    procedure_count: int
    clabsi_count: int
    cauti_count: int
    ssi_count: int
    provisional_clabsi_count: int
    provisional_cauti_count: int
    provisional_ssi_count: int
    predicted_clabsi: float
    predicted_cauti: float
    predicted_ssi: float
    sir_clabsi: Optional[float]
    sir_cauti: Optional[float]
    sir_ssi: Optional[float]
    provisional_sir_clabsi: Optional[float]
    provisional_sir_cauti: Optional[float]
    provisional_sir_ssi: Optional[float]
    sir_flag: str
    status: str
    amendment_count: int
    submitted_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutbreakInvestigation(TypedDict, total=False):
    id: str
    unit_id: str
    organism: str
    origin: str
    detection_window_start: str
    detection_window_end: str
    trigger_case_ids: List[str]
    contributing_case_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IsolationOrder(TypedDict, total=False):
    id: str
    patient_id: str
    unit_id: str
    precaution_type: str
    ordered_by_user_id: str
    ordered_at: str
    started_at: Optional[str]
    discontinued_at: Optional[str]
    status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class IsolationComplianceAudit(TypedDict, total=False):
    id: str
    isolation_order_id: str
    auditor_user_id: str
    observed_at: str
    elements_checked: int
    elements_passed: int
    compliance_pct: float
    outcome: str
    created_at: str
    updated_at: str
    version: int


class HandHygieneObservation(TypedDict, total=False):
    id: str
    unit_id: str
    observer_user_id: str
    observed_at: str
    opportunity_type: str
    action: str
    created_at: str
    updated_at: str
    version: int


class RecordedStage(TypedDict, total=False):
    stage: str
    drawn_at: str
    result: str


class EmployeeExposure(TypedDict, total=False):
    id: str
    employee_id: str
    source_patient_id: Optional[str]
    exposure_type: str
    occurred_at: str
    source_hbv_status: str
    source_hcv_status: str
    source_hiv_status: str
    recorded_stages: List[RecordedStage]
    next_draw_due_at: Optional[str]
    current_stage_overdue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict, total=False):
    id: str
    unit_id: str
    source_type: str
    source_ref_id: str
    description: str
    due_date: str
    evidence_notes: Optional[str]
    failure_count: int
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
