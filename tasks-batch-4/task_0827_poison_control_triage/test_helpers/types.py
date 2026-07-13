"""Domain types: entity TypedDicts, status enums, and the role enum.

All field names are exactly as named in the PRD. ``CaseNote`` is an append-only
documentation record (PRD §2.4) and therefore carries only ``id`` and
``created_at`` — no ``updated_at`` and no ``version``.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SPECIALIST = "Specialist"
    TOXICOLOGIST = "Toxicologist"
    SURVEILLANCE_OFFICER = "SurveillanceOfficer"
    SYSTEM_ADMIN = "SystemAdmin"


class SubstanceCategory(str, Enum):
    ANALGESIC = "ANALGESIC"
    HOUSEHOLD_CHEMICAL = "HOUSEHOLD_CHEMICAL"
    PESTICIDE = "PESTICIDE"
    PLANT = "PLANT"
    PHARMACEUTICAL = "PHARMACEUTICAL"
    HYDROCARBON = "HYDROCARBON"
    HEAVY_METAL = "HEAVY_METAL"


class FacilityType(str, Enum):
    ED = "ED"
    URGENT_CARE = "URGENT_CARE"
    ICU = "ICU"
    CLINIC = "CLINIC"


class FacilityStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    DIVERTING = "DIVERTING"
    OFFLINE = "OFFLINE"


class RiskTier(str, Enum):
    MINIMAL = "MINIMAL"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


class ManagementSetting(str, Enum):
    HOME = "HOME"
    ED = "ED"


class Credential(str, Enum):
    SPI = "SPI"
    TOXICOLOGIST = "TOXICOLOGIST"


class PatientSex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNKNOWN = "UNKNOWN"


class Route(str, Enum):
    INGESTION = "INGESTION"
    INHALATION = "INHALATION"
    DERMAL = "DERMAL"
    OCULAR = "OCULAR"
    INJECTION = "INJECTION"


class SeverityBand(str, Enum):
    MINIMAL = "MINIMAL"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    MONITORING = "MONITORING"
    REFERRED = "REFERRED"
    RETRIAGE = "RETRIAGE"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class AssessmentStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class DispositionType(str, Enum):
    HOME_MANAGEMENT = "HOME_MANAGEMENT"
    ED_REFERRAL = "ED_REFERRAL"


class DispositionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTEMPTED = "ATTEMPTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FollowUpOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    WORSENED = "WORSENED"
    LOST_TO_FOLLOWUP = "LOST_TO_FOLLOWUP"


class ConsultStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETRACTED = "RETRACTED"


class MedicalOutcome(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"


class NoteType(str, Enum):
    INTAKE = "INTAKE"
    CLINICAL = "CLINICAL"
    INTERPRETER = "INTERPRETER"
    DISPOSITION = "DISPOSITION"
    FOLLOWUP = "FOLLOWUP"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Substance(TypedDict):
    id: str
    name: str
    category: str
    toxic_dose_mg_per_kg: float
    onset_hours: float
    reference_route: str
    aggregate_case_count: int
    created_at: str
    updated_at: str
    version: int


class HealthcareFacility(TypedDict):
    id: str
    name: str
    facility_type: str
    status: str
    consult_capacity: int
    active_consult_count: int
    created_at: str
    updated_at: str
    version: int


class Protocol(TypedDict):
    id: str
    risk_tier: str
    management_setting: str
    followup_count: int
    followup_interval_hours: float
    requires_toxicologist: bool
    created_at: str
    updated_at: str
    version: int


class Specialist(TypedDict):
    id: str
    full_name: str
    credential: str
    certification_active: bool
    created_at: str
    updated_at: str
    version: int


class ExposureCase(TypedDict):
    id: str
    patient_age_years: float
    patient_weight_kg: float
    patient_sex: str
    chief_complaint: str
    interpreter_required: bool
    interpreter_language: Optional[str]
    intake_specialist_id: str
    status: str
    risk_tier: Optional[str]
    pending_followup_count: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exposure(TypedDict):
    id: str
    case_id: str
    substance_id: str
    route: str
    dose_range_low_mg: float
    dose_range_high_mg: float
    time_since_exposure_hours: float
    confirmed_dose_mg: Optional[float]
    identified: bool
    toxicity_score: float
    severity_band: str
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    case_id: str
    protocol_id: Optional[str]
    aggregate_score_max: float
    aggregate_score_additive: float
    risk_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict):
    id: str
    case_id: str
    risk_assessment_id: str
    disposition_type: str
    facility_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpCall(TypedDict):
    id: str
    case_id: str
    assigned_specialist_id: str
    sequence_index: int
    scheduled_start: str
    scheduled_end: str
    attempt_count: int
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacilityConsult(TypedDict):
    id: str
    case_id: str
    facility_id: str
    requesting_specialist_id: str
    consult_duration_minutes: float
    confirmed_dose_mg: Optional[float]
    billing_units: float
    status: str
    created_at: str
    updated_at: str
    version: int


class NpdsReport(TypedDict):
    id: str
    case_id: str
    primary_substance_id: str
    medical_outcome: str
    report_status: str
    reported_at: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, only id + created_at
class CaseNote(TypedDict):
    id: str
    case_id: str
    author_ref: str
    note_type: str
    body: str
    created_at: str
