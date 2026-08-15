"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import Optional, TypedDict


class EnrollmentStatus(str, Enum):
    INTAKE = "INTAKE"
    BENEFITS_VERIFIED = "BENEFITS_VERIFIED"
    PA_PENDING = "PA_PENDING"
    PA_DENIED = "PA_DENIED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DENIED_CLOSED = "DENIED_CLOSED"
    DISCONTINUED = "DISCONTINUED"


class PriorAuthorizationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPEALED = "APPEALED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DENIED_FINAL = "DENIED_FINAL"


class CopayAssistanceStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    RELEASED = "RELEASED"


class AssistanceType(str, Enum):
    COPAY_CARD = "COPAY_CARD"
    FOUNDATION = "FOUNDATION"


class ShipmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    SPOILED = "SPOILED"
    CANCELLED = "CANCELLED"


class FillType(str, Enum):
    FIRST_FILL = "FIRST_FILL"
    REFILL = "REFILL"


class NurseVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class AdverseEventStatus(str, Enum):
    REPORTED = "REPORTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class Seriousness(str, Enum):
    SERIOUS = "SERIOUS"
    NON_SERIOUS = "NON_SERIOUS"


class OutcomeReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    HUB_ADMIN = "HubAdmin"
    CASE_MANAGER = "CaseManager"
    FINANCIAL_COUNSELOR = "FinancialCounselor"
    NURSE_EDUCATOR = "NurseEducator"
    PHARMACY_PARTNER = "PharmacyPartner"
    PAYER_REVIEWER = "PayerReviewer"
    MANUFACTURER_MONITOR = "ManufacturerMonitor"


# --- Entity TypedDicts ---
# All entities carry id + created_at + updated_at + version EXCEPT
# BenefitsInvestigation, which is immutable once created and carries only
# id + created_at (PRD section 2.4).


class DrugProgram(TypedDict, total=False):
    id: str
    name: str
    manufacturer_name: str
    diagnosis_code: str
    requires_injection_training: bool
    requires_cold_chain: bool
    max_transit_hours: int
    min_days_between_fills: int
    copay_card_per_fill_cap_cents: int
    copay_card_annual_cap_cents: int
    default_days_supply: int
    created_at: str
    updated_at: str
    version: int


class FoundationPool(TypedDict, total=False):
    id: str
    name: str
    diagnosis_code: str
    total_funding_cents: int
    grant_amount_cents: int
    coverage_pct: int
    start_date: str
    end_date: str
    remaining_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    program_id: str
    patient_ref: str
    diagnosis_code: str
    case_manager_id: str
    status: str
    training_sessions_completed: int
    fills_delivered_count: int
    therapy_start_date: Optional[str]
    payer_accumulated_oop_cents: int
    remaining_oop_cents: Optional[int]
    pdc_confirmed_pct: Optional[float]
    pdc_provisional_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class BenefitsInvestigation(TypedDict, total=False):
    # Immutable record: id + created_at only, NO updated_at / version (PRD 2.4).
    id: str
    created_at: str
    enrollment_id: str
    payer_name: str
    member_id: str
    requires_prior_auth: bool
    plan_has_accumulator: bool
    patient_cost_share_cents: int
    oop_max_cents: int


class PriorAuthorization(TypedDict, total=False):
    id: str
    enrollment_id: str
    clinical_notes: str
    payer_reference: str
    status: str
    appeal_round: int
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CopayAssistance(TypedDict, total=False):
    id: str
    enrollment_id: str
    assistance_type: str
    foundation_pool_id: Optional[str]
    matched_by_user_id: str
    status: str
    per_fill_cap_cents: Optional[int]
    coverage_pct: Optional[int]
    annual_benefit_cap_cents: int
    remaining_annual_benefit_cents: int
    disbursed_cents: int
    returned_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    enrollment_id: str
    fill_number: int
    fill_type: str
    requested_delivery_date: str
    transit_hours: int
    days_supply: int
    status: str
    patient_cost_share_cents: int
    assistance_pay_cents: Optional[int]
    patient_pay_cents: Optional[int]
    payer_accumulator_delta_cents: Optional[int]
    delivered_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NurseVisit(TypedDict, total=False):
    id: str
    enrollment_id: str
    nurse_id: str
    window_start: str
    window_end: str
    status: str
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict, total=False):
    id: str
    enrollment_id: str
    awareness_at: str
    seriousness: str
    description: str
    reported_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict, total=False):
    id: str
    enrollment_id: str
    period_start: str
    period_end: str
    created_by_user_id: str
    status: str
    fills_delivered_count: int
    adverse_event_count: int
    total_assistance_cents: int
    pdc_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int
