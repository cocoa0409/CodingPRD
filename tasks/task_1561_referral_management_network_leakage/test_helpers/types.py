"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class Specialty(str, Enum):
    CARDIOLOGY = "CARDIOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    NEUROLOGY = "NEUROLOGY"
    DERMATOLOGY = "DERMATOLOGY"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"


class Urgency(str, Enum):
    STAT = "STAT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class ReferralStatus(str, Enum):
    PENDING_TRIAGE = "PENDING_TRIAGE"
    NEEDS_INFO = "NEEDS_INFO"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    SCHEDULED = "SCHEDULED"
    VISIT_COMPLETED = "VISIT_COMPLETED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AuthStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    NOT_REQUIRED = "NOT_REQUIRED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_PENDING = "AUTH_PENDING"
    AUTH_OBTAINED = "AUTH_OBTAINED"
    AUTH_DENIED = "AUTH_DENIED"
    AUTH_EXPIRED = "AUTH_EXPIRED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    EXCUSED = "EXCUSED"
    CANCELLED = "CANCELLED"


class ParticipationTier(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"


class PatientChoiceType(str, Enum):
    NONE = "NONE"
    IN_NETWORK_PREFERRED = "IN_NETWORK_PREFERRED"
    OUT_OF_NETWORK_PATIENT_REQUEST = "OUT_OF_NETWORK_PATIENT_REQUEST"
    OUT_OF_NETWORK_CAPACITY = "OUT_OF_NETWORK_CAPACITY"


class CancelReason(str, Enum):
    PATIENT_WENT_OUT_OF_NETWORK = "PATIENT_WENT_OUT_OF_NETWORK"
    PATIENT_DECLINED = "PATIENT_DECLINED"
    CLINICAL_DUPLICATE = "CLINICAL_DUPLICATE"
    OTHER = "OTHER"


class LeakageCategory(str, Enum):
    EXPIRED_UNRESOLVED = "EXPIRED_UNRESOLVED"
    PATIENT_CHOICE_OUT_OF_NETWORK = "PATIENT_CHOICE_OUT_OF_NETWORK"
    CAPACITY_OUT_OF_NETWORK = "CAPACITY_OUT_OF_NETWORK"


class ConfirmationChannel(str, Enum):
    PHONE = "PHONE"
    PORTAL = "PORTAL"
    LETTER = "LETTER"


class LoopClosureOutcome(str, Enum):
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    REOPENED = "REOPENED"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUTREACH_REQUIRED = "OUTREACH_REQUIRED"


class ParticipationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AuthRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AuthRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    REFERRAL_COORDINATOR = "ReferralCoordinator"
    REFERRING_PROVIDER = "ReferringProvider"
    SPECIALIST_PROVIDER = "SpecialistProvider"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# --- Entity TypedDicts -------------------------------------------------------
# Entities carrying the four system-maintained properties (PRD §2.4) include
# id, created_at, updated_at, version. Append-only kinds (ConsultNote,
# LoopClosure, LeakageRecord, ProviderPeriodSnapshot) carry only id + created_at.


class ReferringProvider(TypedDict):
    id: str
    name: str
    npi: str
    specialty: str
    status: str
    leakage_event_count: int
    watch_flag: bool
    created_at: str
    updated_at: str
    version: int


class SpecialistProvider(TypedDict):
    id: str
    name: str
    npi: str
    specialty: str
    base_region: str
    weekly_capacity: int
    accepts_new_patients: bool
    accepts_urgent: bool
    booked_appointments_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    plan_code: str
    payer_name: str
    payer_mix_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    region: str
    insurance_plan_id: str
    no_show_strikes: int
    status: str
    no_show_risk_confirmed: float
    no_show_risk_forward: float
    created_at: str
    updated_at: str
    version: int


class NetworkParticipation(TypedDict):
    id: str
    specialist_id: str
    insurance_plan_id: str
    tier: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthRule(TypedDict):
    id: str
    specialty: str
    insurance_plan_id: str
    requires_auth: bool
    auth_validity_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referring_provider_id: str
    patient_id: str
    specialty: str
    diagnosis_code: str
    urgency: str
    insurance_plan_id: Optional[str]
    in_network_preference: bool
    patient_choice_documented: bool
    patient_choice_type: str
    patient_choice_note: str
    target_specialist_id: Optional[str]
    match_score: Optional[int]
    status: str
    auth_status: str
    triaged_at: Optional[str]
    sla_due_at: Optional[str]
    age_days: int
    ever_scheduled: bool
    escalation_flag: bool
    leaked: bool
    out_of_network: bool
    cancel_reason: Optional[str]
    needs_info_note: str
    created_at: str
    updated_at: str
    version: int


class AuthorizationRecord(TypedDict):
    id: str
    referral_id: str
    auth_number: str
    obtained_at: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    referral_id: str
    specialist_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    confirmation_channel: Optional[str]
    confirmed_at: Optional[str]
    completed_at: Optional[str]
    superseded: bool
    excuse_reason: str
    scheduled_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ConsultNote(TypedDict):
    # Append-only (PRD §2.4): no updated_at, no version.
    id: str
    referral_id: str
    appointment_id: str
    author_specialist_id: str
    findings_summary: str
    follow_up_recommended: bool
    note_sequence: int
    returned_within_sla: bool
    created_at: str


class LoopClosure(TypedDict):
    # Append-only (PRD §2.4): no updated_at, no version.
    id: str
    referral_id: str
    outcome: str
    verification_note: str
    verifier_user_id: str
    created_at: str


class LeakageRecord(TypedDict):
    # Append-only (PRD §2.4): no updated_at, no version.
    id: str
    referral_id: str
    category: str
    attributed_referring_provider_id: str
    estimated_value_cents: int
    created_at: str


class ProviderPeriodSnapshot(TypedDict):
    # Frozen row (PRD §2.4): no updated_at, no version.
    id: str
    referring_provider_id: str
    period_start: str
    period_end: str
    intake_count: int
    completed_count: int
    scheduled_basis_count: int
    leaked_count: int
    conversion_rate_intake: float
    conversion_rate_scheduled: float
    leakage_rate: float
    estimated_leakage_exposure_cents: int
    closed_at: str
    created_at: str
