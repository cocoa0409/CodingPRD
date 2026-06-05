"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    CLINICAL_DIRECTOR = "ClinicalDirector"
    THERAPIST = "Therapist"
    BILLER = "Biller"
    FRONT_DESK = "FrontDesk"


class CredentialStatus(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    SUPERVISED_PRACTICE = "SUPERVISED_PRACTICE"
    INDEPENDENT = "INDEPENDENT"
    SUSPENDED = "SUSPENDED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SupervisionLogStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_CLINICAL_HOLD = "ON_CLINICAL_HOLD"
    DISCHARGED = "DISCHARGED"


class CostShareModel(str, Enum):
    COPAY = "COPAY"
    COINSURANCE = "COINSURANCE"


class CptCode(str, Enum):
    INTAKE_90791 = "90791"
    THERAPY_90834 = "90834"


class Modality(str, Enum):
    IN_PERSON = "IN_PERSON"
    TELEHEALTH = "TELEHEALTH"


class PaymentPath(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RENDERED = "RENDERED"
    COMPLETED = "COMPLETED"
    CLAIMED = "CLAIMED"
    WRITTEN_OFF = "WRITTEN_OFF"
    CANCELLED = "CANCELLED"


class ClinicalNoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    CO_SIGNED = "CO_SIGNED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    RESUBMITTED = "RESUBMITTED"
    VOID = "VOID"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class CrisisAssessmentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


# --- Entities (all carry common_fields: true → id/created_at/updated_at/version) ---

class Therapist(TypedDict):
    id: str
    full_name: str
    home_state_code: Optional[str]
    credential_status: str
    requires_supervision: bool
    verified_direct_hours: float
    projected_direct_hours: float
    verified_supervision_hours: float
    supervisor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateLicense(TypedDict):
    id: str
    therapist_id: str
    state_code: str
    license_number: str
    status: str
    expires_on: str
    telehealth_authorized: bool
    created_at: str
    updated_at: str
    version: int


class SupervisionLog(TypedDict):
    id: str
    therapist_id: str
    supervisor_id: str
    hours: float
    logged_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    location_state_code: str
    annual_household_income: float
    household_size: int
    fpl_percent: float
    sliding_fee_multiplier: float
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    patient_id: str
    contract_id: str
    cost_share_model: str
    copay_cents: int
    coinsurance_rate: float
    deductible_total_cents: int
    deductible_met_cents: int
    created_at: str
    updated_at: str
    version: int


class PayerContract(TypedDict):
    id: str
    payer_name: str
    in_network: bool
    contracted_rate_90791_cents: int
    contracted_rate_90834_cents: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    therapist_id: str
    patient_id: str
    cpt_code: str
    modality: str
    start_at: str
    duration_minutes: int
    status: str
    payment_path: str
    insurance_policy_id: Optional[str]
    patient_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ClinicalNote(TypedDict):
    id: str
    appointment_id: str
    narrative: str
    status: str
    signed_by_id: Optional[str]
    cosigned_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    appointment_id: str
    insurance_policy_id: str
    cpt_code: str
    billed_charge_cents: int
    allowed_amount_cents: int
    deductible_applied_cents: int
    patient_responsibility_cents: int
    payer_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrisisAssessment(TypedDict):
    id: str
    patient_id: str
    therapist_id: str
    ideation_score: int
    plan_score: int
    means_access_score: int
    prior_attempts_score: int
    risk_score: float
    risk_band: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyPlan(TypedDict):
    id: str
    crisis_assessment_id: str
    warning_signs: str
    coping_strategies: str
    emergency_contacts: List[str]
    created_at: str
    updated_at: str
    version: int
