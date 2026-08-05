"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full set of system-managed fields
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---------------------------------------------------------------

class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    CLINICIAN = "Clinician"
    CLINIC_SUPERVISOR = "ClinicSupervisor"


# --- Status enums ------------------------------------------------------------

class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REASSESSMENT = "UNDER_REASSESSMENT"
    DISCHARGED = "DISCHARGED"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AttendanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    REVERSED = "REVERSED"


class HomeSafetyStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class DeviceReferralStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    DISPENSED = "DISPENSED"


class DeviceReferralSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_HAZARD = "AUTO_HAZARD"


class LinkageStatus(str, Enum):
    REFERRED = "REFERRED"
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ReassessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


# --- Entity TypedDicts (all common_fields: true) -----------------------------

class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    insurance_member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    referral_source: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    full_name: str
    discipline: str
    npi: str
    created_at: str
    updated_at: str
    version: int


class TherapyRoom(TypedDict):
    id: str
    name: str
    room_type: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    patient_id: str
    referral_id: str
    clinician_id: str
    gait_speed_m_s: float
    tug_seconds: float
    berg_balance_score: int
    medication_count: int
    self_report_fall_count: int
    screening_score: int
    clinical_score: Optional[int]
    fall_risk_tier: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    patient_id: str
    assessment_id: str
    fall_risk_tier: str
    target_visits: int
    estimated_patient_responsibility_cents: Optional[int]
    patient_responsibility_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceAuthorization(TypedDict):
    id: str
    patient_id: str
    care_plan_id: str
    payer_name: str
    visits_authorized: int
    allowed_amount_cents: int
    coinsurance_pct: float
    visits_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    care_plan_id: str
    clinician_id: str
    room_id: str
    authorization_id: str
    scheduled_start: str
    scheduled_end: str
    cpt_code: str
    copay_cents: int
    attendance_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class HomeSafetyEvaluation(TypedDict):
    id: str
    patient_id: str
    care_plan_id: str
    loose_rugs: int
    poor_lighting_rooms: int
    missing_grab_bars: int
    unsecured_stairs: int
    clutter_pathways: int
    home_hazard_score: Optional[int]
    hazard_tier: Optional[str]
    generated_device_referral_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssistiveDeviceReferral(TypedDict):
    id: str
    patient_id: str
    care_plan_id: str
    home_safety_evaluation_id: Optional[str]
    device_type: str
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunityProgramLinkage(TypedDict):
    id: str
    patient_id: str
    care_plan_id: str
    assessment_id: str
    program_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reassessment(TypedDict):
    id: str
    care_plan_id: str
    clinician_id: str
    gait_speed_m_s: float
    tug_seconds: float
    berg_balance_score: int
    medication_count: int
    self_report_fall_count: int
    clinical_score: Optional[int]
    fall_risk_tier: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
