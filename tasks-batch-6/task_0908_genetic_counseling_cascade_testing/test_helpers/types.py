"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the Genetic Counseling & Cascade Testing PRD. Every resource in this
system is mutable and carries id / created_at / updated_at / version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    GENETIC_COUNSELOR = "GeneticCounselor"
    LAB_TECHNICIAN = "LabTechnician"
    BILLING_SPECIALIST = "BillingSpecialist"
    PROGRAM_ADMIN = "ProgramAdmin"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class CaseClinicalStatus(str, Enum):
    INTAKE = "INTAKE"
    RISK_ASSESSED = "RISK_ASSESSED"
    TESTING = "TESTING"
    DISCLOSED = "DISCLOSED"
    SURVEILLANCE = "SURVEILLANCE"
    WITHDRAWN = "WITHDRAWN"


class CaseBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PENDING_AUTH = "PENDING_AUTH"
    AUTHORIZED = "AUTHORIZED"
    BILLED = "BILLED"
    PAID = "PAID"
    DENIED = "DENIED"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RESULTED = "RESULTED"
    CANCELLED = "CANCELLED"


class ResultStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    DISCLOSED = "DISCLOSED"


class InvitationStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    DECLINED = "DECLINED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class CarrierResult(str, Enum):
    POSITIVE_PATHOGENIC = "POSITIVE_PATHOGENIC"
    NEGATIVE = "NEGATIVE"
    VUS = "VUS"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Family(TypedDict):
    id: str
    family_name: str
    outreach_budget_cents: int
    outreach_reserved_cents: int
    outreach_spent_cents: int
    outreach_available_cents: int
    cascade_invitations_sent_count: int
    cascade_cases_count: int
    cascade_uptake_pct: float
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict):
    id: str
    full_name: str
    npi: str
    created_at: str
    updated_at: str
    version: int


class Lab(TypedDict):
    id: str
    lab_name: str
    max_concurrent_capacity: int
    turnaround_days: int
    current_processing_load: int
    created_at: str
    updated_at: str
    version: int


class CounselingCase(TypedDict):
    id: str
    family_id: str
    assigned_counselor_id: str
    originating_invitation_id: Optional[str]
    patient_name: str
    patient_dob: str
    sex: str
    ancestry: str
    relationship_to_proband: str
    referral_reason: str
    familial_variant_known: bool
    covered_sessions: int
    prior_risk_pct: Optional[float]
    residual_risk_pct: Optional[float]
    risk_tier: Optional[str]
    carrier_result: Optional[str]
    sessions_used: int
    sessions_remaining: int
    clinical_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class PedigreeMember(TypedDict):
    id: str
    counseling_case_id: str
    related_member_id: Optional[str]
    relationship: str
    degree: int
    affected: bool
    age_of_onset: Optional[int]
    deceased: bool
    is_at_risk: bool
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict):
    id: str
    counseling_case_id: str
    consent_type: str
    signed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CounselingSession(TypedDict):
    id: str
    counseling_case_id: str
    counselor_id: str
    session_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestOrder(TypedDict):
    id: str
    counseling_case_id: str
    lab_id: str
    panel_name: str
    cpt_codes: List[str]
    list_price_cents: int
    processing_start: str
    processing_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestResult(TypedDict):
    id: str
    test_order_id: str
    gene: str
    variant: str
    classification: str
    is_actionable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CascadeInvitation(TypedDict):
    id: str
    family_id: str
    proband_case_id: str
    pedigree_member_id: str
    relative_name: str
    relationship: str
    degree: int
    contact_method: str
    estimated_cost_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    counseling_case_id: str
    test_order_id: str
    payer_name: str
    member_number: str
    coverage_pct: float
    estimated_allowed_rate: float
    line_items: List[dict]
    billed_total_cents: int
    estimated_allowed_cents: Optional[int]
    final_allowed_cents: Optional[int]
    patient_responsibility_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveillancePlan(TypedDict):
    id: str
    counseling_case_id: str
    risk_tier: str
    modalities: List[str]
    screening_interval_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    counseling_case_id: str
    surveillance_plan_id: Optional[str]
    specialty: str
    reason: str
    urgency: str
    status: str
    created_at: str
    updated_at: str
    version: int
