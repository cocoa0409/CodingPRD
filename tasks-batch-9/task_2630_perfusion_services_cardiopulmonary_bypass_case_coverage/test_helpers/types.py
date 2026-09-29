"""Domain types for the Perfusion Bypass Case Coverage API.

Entity TypedDicts, status enums and the role enum, derived from the PRD's
entity descriptions in sections 3.1 through 3.10.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CONTRACT_ADMIN = "ContractAdmin"
    CHIEF_PERFUSIONIST = "ChiefPerfusionist"
    PERFUSIONIST = "Perfusionist"
    BIOMED_TECH = "BiomedTech"
    SURGEON = "Surgeon"


class StaffingModel(str, Enum):
    PER_CASE = "PER_CASE"
    COVERAGE_PLUS_PER_CASE = "COVERAGE_PLUS_PER_CASE"
    FULL_COVERAGE = "FULL_COVERAGE"


class CoveragePosture(str, Enum):
    COVERED = "COVERED"
    THIN = "THIN"
    UNCOVERED = "UNCOVERED"


class SurgeonSpecialty(str, Enum):
    ADULT_CARDIAC = "ADULT_CARDIAC"
    PEDIATRIC_CARDIAC = "PEDIATRIC_CARDIAC"
    TRANSPLANT = "TRANSPLANT"


class SurgeonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProcedureType(str, Enum):
    CABG = "CABG"
    VALVE = "VALVE"
    AORTIC_ARCH = "AORTIC_ARCH"
    TRANSPLANT = "TRANSPLANT"
    VAD_IMPLANT = "VAD_IMPLANT"
    PEDIATRIC_SWITCH = "PEDIATRIC_SWITCH"


class PreferenceCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class BloodManagementProtocol(str, Enum):
    STANDARD = "STANDARD"
    ANTIFIBRINOLYTIC = "ANTIFIBRINOLYTIC"
    JEHOVAH_WITNESS_BLOODLESS = "JEHOVAH_WITNESS_BLOODLESS"
    PEDIATRIC_MINIPRIME = "PEDIATRIC_MINIPRIME"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEAVE = "LEAVE"
    TERMINATED = "TERMINATED"


class ReadinessVariant(str, Enum):
    ADMISSION = "ADMISSION"
    AUDIT = "AUDIT"


class CertCode(str, Enum):
    CCP = "CCP"
    CES_A = "CES_A"
    ECMO_SPEC = "ECMO_SPEC"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class CeCategory(str, Enum):
    CLINICAL = "CLINICAL"
    TECHNICAL = "TECHNICAL"
    SAFETY = "SAFETY"
    ETHICS = "ETHICS"


class AccreditationBody(str, Enum):
    ABCP = "ABCP"
    AMSECT = "AMSECT"
    OTHER = "OTHER"


class CeActivityStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class DeviceClass(str, Enum):
    HEART_LUNG_MACHINE = "HEART_LUNG_MACHINE"
    ECMO_CONSOLE = "ECMO_CONSOLE"
    CELL_SAVER = "CELL_SAVER"
    HEATER_COOLER = "HEATER_COOLER"


class DeviceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    NEEDS_SERVICE = "NEEDS_SERVICE"


class DeviceEventCode(str, Enum):
    ALARM_CRITICAL = "ALARM_CRITICAL"
    ALARM_ADVISORY = "ALARM_ADVISORY"
    RUNTIME_TICK = "RUNTIME_TICK"
    SELF_TEST_PASS = "SELF_TEST_PASS"
    SELF_TEST_FAIL = "SELF_TEST_FAIL"
    SERVICE_COMPLETED = "SERVICE_COMPLETED"


class SlotType(str, Enum):
    PRIMARY_CALL = "PRIMARY_CALL"
    BACKUP_CALL = "BACKUP_CALL"
    ECMO_RELIEF = "ECMO_RELIEF"


class SlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class Acuity(str, Enum):
    ELECTIVE = "ELECTIVE"
    URGENT = "URGENT"
    EMERGENT = "EMERGENT"


class BypassStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    STAFFED = "STAFFED"
    PACK_CONFIGURED = "PACK_CONFIGURED"
    SETUP_VERIFIED = "SETUP_VERIFIED"
    ON_BYPASS = "ON_BYPASS"
    OFF_BYPASS = "OFF_BYPASS"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONAL_ACCRUED = "PROVISIONAL_ACCRUED"
    FINAL_ACCRUED = "FINAL_ACCRUED"
    INVOICED = "INVOICED"
    CREDITED = "CREDITED"


class ReadinessFlag(str, Enum):
    NONE = "NONE"
    DEVICE_FALLBACK_REQUIRED = "DEVICE_FALLBACK_REQUIRED"


class PackApprovalStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChecklistStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    INVALIDATED = "INVALIDATED"


class EcmoMode(str, Enum):
    VV = "VV"
    VA = "VA"
    VAV = "VAV"


class EcmoRunStatus(str, Enum):
    RUNNING = "RUNNING"
    RELIEF_PENDING = "RELIEF_PENDING"
    DECANNULATED = "DECANNULATED"


class IncidentSeverity(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SENTINEL = "SENTINEL"


class IncidentCategory(str, Enum):
    CIRCUIT = "CIRCUIT"
    GAS_EXCHANGE = "GAS_EXCHANGE"
    ANTICOAGULATION = "ANTICOAGULATION"
    DEVICE_FAILURE = "DEVICE_FAILURE"
    BLOOD_MANAGEMENT = "BLOOD_MANAGEMENT"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    CLOSED_WITH_ACTION = "CLOSED_WITH_ACTION"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class IncidentFinding(str, Enum):
    NONE = "NONE"
    ISOLATED = "ISOLATED"
    SYSTEMIC = "SYSTEMIC"


# ─── Entity TypedDicts ────────────────────────────────
# Every resource carries id, created_at, updated_at and version, with the single
# exception of DeviceEventLog, which carries only id and created_at.


class HospitalContract(TypedDict):
    id: str
    hospital_name: str
    staffing_model: str
    monthly_coverage_fee_cents: int
    per_case_fee_cents: int
    ecmo_hourly_fee_cents: int
    prolonged_surcharge_pct: float
    prolonged_pump_threshold_minutes: int
    disposable_markup_pct: float
    disposable_discount_pct: float
    monthly_case_cap: int
    accrued_case_fee_cents: int
    accrued_case_count: int
    coverage_posture: str
    last_settlement_period: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Surgeon(TypedDict):
    id: str
    full_name: str
    npi_code: str
    specialty: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PreferenceCard(TypedDict):
    id: str
    surgeon_id: str
    procedure_type: str
    revision: int
    status: str
    standard_pump_minutes: int
    prime_volume_ml: int
    pack_line_items: List[Dict[str, Any]]
    required_safety_check_codes: List[str]
    blood_management_protocol: str
    min_hematocrit_pct: float
    created_at: str
    updated_at: str
    version: int


class Perfusionist(TypedDict):
    id: str
    full_name: str
    employee_code: str
    employment_status: str
    is_chief: bool
    ecmo_privileged: bool
    career_case_count: int
    ce_credits_verified: float
    ce_credits_pending: float
    readiness_score: float
    readiness_variant_last: Optional[str]
    consecutive_case_count_24h: int
    ecmo_hours_rolling_7d: float
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    perfusionist_id: str
    cert_code: str
    status: str
    issued_on: str
    expires_on: str
    cycle_credit_requirement: float
    remediation_credits_required: float
    probation_credits_banked: float
    probation_count: int
    created_at: str
    updated_at: str
    version: int


class CeActivity(TypedDict):
    id: str
    perfusionist_id: str
    category: str
    credit_hours: float
    activity_date: str
    accreditation_body: str
    status: str
    counted_toward_remediation: bool
    created_at: str
    updated_at: str
    version: int


class PerfusionDevice(TypedDict):
    id: str
    contract_id: str
    asset_tag: str
    device_class: str
    status: str
    backup_device_id: Optional[str]
    service_interval_hours: int
    runtime_hours_since_service: float
    alarm_count_since_service: int
    last_service_completed_at: Optional[str]
    open_reservation_count: int
    created_at: str
    updated_at: str
    version: int


class DeviceEventLog(TypedDict):
    """A captured device event is immutable: it carries only id and created_at."""
    id: str
    device_id: str
    event_code: str
    runtime_hours_delta: float
    recorded_by_user_id: str
    detail: Optional[str]
    created_at: str


class CallRotationSlot(TypedDict):
    id: str
    contract_id: str
    perfusionist_id: str
    slot_type: str
    window_start: str
    window_end: str
    status: str
    consumed: bool
    created_at: str
    updated_at: str
    version: int


class BypassCase(TypedDict):
    id: str
    contract_id: str
    surgeon_id: str
    assigned_perfusionist_id: Optional[str]
    primary_device_id: Optional[str]
    backup_device_id: Optional[str]
    procedure_type: str
    acuity: str
    scheduled_start: str
    scheduled_end: str
    bypass_status: str
    billing_status: str
    bypass_started_at: Optional[str]
    bypass_ended_at: Optional[str]
    pump_time_minutes: Optional[int]
    cross_clamp_minutes: Optional[int]
    lowest_hematocrit_pct: Optional[float]
    adverse_event_count: int
    provisional_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    accrued_fee_cents: int
    readiness_flag: str
    setup_verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisposablePack(TypedDict):
    id: str
    case_id: str
    applied_preference_card_id: str
    line_items: List[Dict[str, Any]]
    substitutions: List[Dict[str, Any]]
    requires_surgeon_approval: bool
    approval_status: str
    pack_cost_cents: int
    prime_volume_ml: int
    created_at: str
    updated_at: str
    version: int


class PumpChecklist(TypedDict):
    id: str
    case_id: str
    verified_by_perfusionist_id: Optional[str]
    check_results: List[Dict[str, Any]]
    blood_management_protocol: str
    hematocrit_pct: float
    blood_mgmt_signoff: bool
    status: str
    verified_at: Optional[str]
    missing_check_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class EcmoRun(TypedDict):
    id: str
    case_id: str
    primary_perfusionist_id: str
    relief_slot_id: Optional[str]
    mode: str
    cannulated_at: str
    last_handoff_at: Optional[str]
    decannulated_at: Optional[str]
    status: str
    uninterrupted_minutes: float
    billable_hours: int
    staffing_breach: bool
    ecmo_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    case_id: str
    involved_perfusionist_id: str
    filed_by_perfusionist_id: str
    closed_by_perfusionist_id: Optional[str]
    severity: str
    category: str
    narrative: str
    status: str
    return_count: int
    reviewed_readiness_score: Optional[float]
    finding: str
    corrective_action_required: bool
    created_at: str
    updated_at: str
    version: int
