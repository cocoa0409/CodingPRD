"""Domain types: entity TypedDicts, status enums, role enum.

All eight entity types in this system carry the full common-field set
(id, created_at, updated_at, version); none omit updated_at or version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Status enums ---

class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDING_AUTH = "PENDING_AUTH"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SleepBedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class StudyOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SCORED = "SCORED"
    INTERPRETED = "INTERPRETED"
    CANCELLED = "CANCELLED"


class StudyModality(str, Enum):
    IN_LAB_PSG = "IN_LAB_PSG"
    HSAT = "HSAT"
    IN_LAB_TITRATION = "IN_LAB_TITRATION"


class Severity(str, Enum):
    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ScoringReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    RETURNED = "RETURNED"


class DMEOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class DeviceType(str, Enum):
    CPAP = "CPAP"
    APAP = "APAP"
    BIPAP = "BIPAP"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    SCHEDULING_COORDINATOR = "SchedulingCoordinator"
    SLEEP_TECHNOLOGIST = "SleepTechnologist"
    PHYSICIAN = "Physician"
    DME_COORDINATOR = "DMECoordinator"
    PATIENT = "Patient"


# --- Entity TypedDicts (all common_fields: true) ---

class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    insurance_payer: str
    baseline_epworth_score: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    referring_provider_npi: str
    requested_modality: str
    clinical_indication: str
    prior_auth_required: bool
    prior_auth_number: Optional[str]
    prior_auth_expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SleepBed(TypedDict):
    id: str
    bed_label: str
    turnover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StudyOrder(TypedDict):
    id: str
    referral_id: str
    bed_id: Optional[str]
    modality: str
    night_start_utc: Optional[str]
    night_end_utc: Optional[str]
    total_recording_minutes: Optional[int]
    respiratory_event_count: Optional[int]
    titration_optimal_cmh2o: Optional[float]
    ahi: Optional[float]
    severity: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoringReport(TypedDict):
    id: str
    study_order_id: str
    scored_by_tech_id: str
    ahi_snapshot: float
    severity_snapshot: str
    interpretation_text: Optional[str]
    physician_recommends_cpap: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DMEOrder(TypedDict):
    id: str
    study_order_id: str
    supersedes_dme_order_id: Optional[str]
    device_type: str
    prescribed_pressure_cmh2o: float
    resupply_cycle_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceRecord(TypedDict):
    id: str
    dme_order_id: str
    window_start_utc: str
    window_end_utc: str
    nights_used_4h_plus: int
    total_usage_minutes: int
    adherent: bool
    created_at: str
    updated_at: str
    version: int


class FollowUp(TypedDict):
    id: str
    study_order_id: str
    scheduled_for_utc: str
    post_treatment_epworth_score: Optional[int]
    epworth_improvement: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
