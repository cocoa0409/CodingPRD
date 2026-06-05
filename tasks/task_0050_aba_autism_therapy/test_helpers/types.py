"""Domain types: entity TypedDicts, status enums, and the role enum.

All eight primary resources are full mutable resources carrying
id/created_at/updated_at/version, per the PRD common-resource-properties rule.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────

class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProviderCredential(str, Enum):
    BCBA = "BCBA"
    RBT = "RBT"


class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"


class SeverityLevel(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    RETIRED = "RETIRED"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"


class SupervisionStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class ServiceLine(str, Enum):
    DIRECT_THERAPY = "DIRECT_THERAPY"
    SUPERVISION = "SUPERVISION"
    PARENT_TRAINING = "PARENT_TRAINING"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    NONE = "NONE"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    SUPERVISION_DEFICIENT = "SUPERVISION_DEFICIENT"
    DUPLICATE = "DUPLICATE"


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    BCBA = "BCBA"
    RBT = "RBT"
    BILLING_SPECIALIST = "BillingSpecialist"
    CAREGIVER = "Caregiver"


# ─── Entity TypedDicts (all common_fields: true) ──────────────

class Client(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    caregiver_user_id: str
    insurance_payer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    name: str
    allowed_rate_cents: int
    coinsurance_pct: float
    supervision_ratio_pct: float
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    full_name: str
    credential: str
    npi: str
    supervising_bcba_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DiagnosticEvaluation(TypedDict):
    id: str
    client_id: str
    evaluator_bcba_id: str
    assessment_score: int
    severity_level: Optional[str]
    recommended_weekly_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    client_id: str
    evaluation_id: str
    author_bcba_id: str
    requested_direct_units: int
    requested_supervision_units: int
    requested_parent_training_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    treatment_plan_id: str
    payer_id: str
    authorized_direct_units: int
    authorized_supervision_units: int
    authorized_parent_training_units: int
    period_start: str
    period_end: str
    reserved_direct_units: int
    delivered_direct_units: int
    reserved_supervision_units: int
    delivered_supervision_units: int
    reserved_parent_training_units: int
    delivered_parent_training_units: int
    remaining_direct_units: int
    supervision_status: str
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TherapySession(TypedDict):
    id: str
    authorization_id: str
    provider_id: str
    service_line: str
    scheduled_start: str
    scheduled_end: str
    scheduled_units: int
    delivered_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    session_id: str
    payer_id: str
    billed_cents: int
    allowed_cents: int
    patient_responsibility_cents: int
    payer_paid_cents: int
    denial_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
