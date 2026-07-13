"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles -----------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CARE_COORDINATOR = "CareCoordinator"
    PARAMEDIC = "Paramedic"
    CLINICIAN = "Clinician"
    BILLING_SPECIALIST = "BillingSpecialist"
    PAYER_REVIEWER = "PayerReviewer"


# --- Status enums ----------------------------------------------------------
class PilotProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"
    WITHDRAWN = "WITHDRAWN"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    CLOSED = "CLOSED"


class HomeVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TelehealthSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MedReconciliationStatus(str, Enum):
    DRAFTED = "DRAFTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    RECONCILED = "RECONCILED"
    FLAGGED = "FLAGGED"


class SocialNeedsReferralStatus(str, Enum):
    OPEN = "OPEN"
    REFERRED = "REFERRED"
    RESOLVED = "RESOLVED"
    UNMET = "UNMET"


class BillingClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class ProviderType(str, Enum):
    PARAMEDIC = "PARAMEDIC"
    CLINICIAN = "CLINICIAN"
    COORDINATOR = "COORDINATOR"
    BILLER = "BILLER"


class PayerType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Payer(TypedDict):
    id: str
    name: str
    payer_type: str
    created_at: str
    updated_at: str
    version: int


class PilotProgram(TypedDict):
    id: str
    name: str
    payer_id: str
    status: str
    budget_cap_cents: int
    available_budget_cents: int
    committed_spend_cents: int
    enrollment_cap: int
    active_enrollment_count: int
    remaining_slots: int
    per_visit_rate_cents: int
    per_telehealth_rate_cents: int
    diversion_bonus_cents: int
    readmission_penalty_cents: int
    diversion_target_max_ed_visits: int
    avg_ed_cost_cents: int
    diversion_credit_pct: float
    start_date: str
    end_date: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    provider_type: str
    npi: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    baseline_ed_visits_12mo: int
    chronic_conditions_count: int
    consent_on_file: bool
    risk_score: int
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    program_id: str
    referring_source: str
    status: str
    screened_risk_tier: str
    decline_reason: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    patient_id: str
    program_id: str
    referral_id: str
    status: str
    enrolled_at: str
    discharged_at: str
    billed_amount_cents: int
    revision_count: int
    needs_review: bool
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    enrollment_id: str
    authoring_clinician_id: str
    cosigner_clinician_id: str
    risk_level: str
    goals: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HomeVisit(TypedDict):
    id: str
    enrollment_id: str
    care_plan_id: str
    provider_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    systolic_bp: int
    diastolic_bp: int
    heart_rate: int
    billable: bool
    created_at: str
    updated_at: str
    version: int


class TelehealthSession(TypedDict):
    id: str
    enrollment_id: str
    patient_id: str
    provider_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    systolic_bp: int
    diastolic_bp: int
    heart_rate: int
    billable: bool
    created_at: str
    updated_at: str
    version: int


class MedReconciliation(TypedDict):
    id: str
    enrollment_id: str
    home_visit_id: str
    medications: List[str]
    discrepancy_count: int
    status: str
    review_outcome: str
    created_at: str
    updated_at: str
    version: int


class SocialNeedsReferral(TypedDict):
    id: str
    enrollment_id: str
    domain: str
    status: str
    partner_org: str
    resolution_status: str
    resolution_note: str
    created_at: str
    updated_at: str
    version: int


# EDEvent — common_fields: false — carries ONLY id + created_at (no updated_at/version)
class EDEvent(TypedDict):
    id: str
    patient_id: str
    event_type: str
    event_date: str
    discharge_date: str
    is_readmission: bool
    created_at: str


class BillingClaim(TypedDict):
    id: str
    enrollment_id: str
    program_id: str
    payer_id: str
    period_start: str
    period_end: str
    status: str
    provisional_amount_cents: int
    final_amount_cents: int
    amount_cents: int
    billable_visit_count: int
    billable_telehealth_count: int
    denial_reason: str
    created_at: str
    updated_at: str
    version: int
