"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the Cardiac & Pulmonary Rehab PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    REFERRING_PHYSICIAN = "ReferringPhysician"
    REHAB_COORDINATOR = "RehabCoordinator"
    REHAB_CLINICIAN = "RehabClinician"
    BILLING_SPECIALIST = "BillingSpecialist"


# --- Status / enum value sets ---
class ProgramType(str, Enum):
    CARDIAC = "CARDIAC"
    PULMONARY = "PULMONARY"


class RiskStratification(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    DISCHARGED = "DISCHARGED"
    WITHDRAWN = "WITHDRAWN"


class Phase(str, Enum):
    PHASE_I = "PHASE_I"
    PHASE_II = "PHASE_II"
    PHASE_III = "PHASE_III"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXHAUSTED = "EXHAUSTED"


class SessionType(str, Enum):
    MONITORED_EXERCISE = "MONITORED_EXERCISE"
    EDUCATION = "EDUCATION"
    ASSESSMENT = "ASSESSMENT"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class StationType(str, Enum):
    TELEMETRY = "TELEMETRY"
    STANDARD = "STANDARD"


class Credential(str, Enum):
    RN = "RN"
    RRT = "RRT"
    EP = "EP"


class CarePlanItemType(str, Enum):
    EDUCATION_MODULE = "EDUCATION_MODULE"
    GOAL = "GOAL"


class CarePlanItemStatus(str, Enum):
    OPEN = "OPEN"
    ACHIEVED = "ACHIEVED"
    NOT_ACHIEVED = "NOT_ACHIEVED"
    WAIVED = "WAIVED"


class OutcomeTiming(str, Enum):
    BASELINE = "BASELINE"
    DISCHARGE = "DISCHARGE"


class OutcomeStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class AssessmentType(str, Enum):
    SIX_MINUTE_WALK = "SIX_MINUTE_WALK"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class MaintenanceTier(str, Enum):
    STANDARD = "STANDARD"
    INTENSIVE = "INTENSIVE"


class MaintenanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all carry common fields: id/created_at/updated_at/version) ---
class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    specialty: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    full_name: str
    credential: str
    created_at: str
    updated_at: str
    version: int


class MonitoringStation(TypedDict):
    id: str
    name: str
    station_type: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    physician_id: str
    program_type: str
    indication: str
    risk_stratification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RehabProgram(TypedDict):
    id: str
    patient_id: str
    referral_id: str
    program_type: str
    risk_stratification: str
    current_phase: str
    authorized_session_cap: int
    sessions_used: int
    sessions_scheduled: int
    sessions_remaining_authorized: int
    consecutive_missed_count: int
    total_billed_cents: int
    total_reimbursed_cents: int
    total_patient_responsibility_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceAuthorization(TypedDict):
    id: str
    program_id: str
    payer_name: str
    authorized_visits: int
    allowed_amount_cents: int
    copay_cents: int
    visits_billed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RehabSession(TypedDict, total=False):
    id: str
    program_id: str
    clinician_id: str
    station_id: str
    session_type: str
    phase: str
    scheduled_start: str
    scheduled_end: str
    pre_hr: Optional[int]
    post_hr: Optional[int]
    post_spo2: Optional[int]
    rpe: Optional[int]
    exercise_minutes: Optional[int]
    adverse_event: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlanItem(TypedDict, total=False):
    id: str
    program_id: str
    item_type: str
    title: str
    target_description: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeAssessment(TypedDict, total=False):
    id: str
    program_id: str
    assessment_type: str
    timing: str
    distance_meters: int
    improvement_meters: Optional[int]
    improvement_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingClaim(TypedDict, total=False):
    id: str
    program_id: str
    session_id: str
    authorization_id: str
    billed_amount_cents: int
    estimated_reimbursement_cents: int
    estimated_patient_responsibility_cents: int
    adjudicated_reimbursement_cents: Optional[int]
    patient_responsibility_cents: int
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceProgram(TypedDict):
    id: str
    program_id: str
    patient_id: str
    tier: str
    monthly_visit_allowance: int
    status: str
    created_at: str
    updated_at: str
    version: int
