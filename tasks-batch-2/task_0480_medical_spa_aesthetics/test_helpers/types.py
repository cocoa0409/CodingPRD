"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Entities carrying id/created_at/updated_at/
version are the standard mutable resources; the ConsentPhoto is an immutable
event record (§2.4) and so carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum (§2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    PROVIDER = "Provider"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ProviderRoleKind(str, Enum):
    INJECTOR = "INJECTOR"
    MEDICAL_DIRECTOR = "MEDICAL_DIRECTOR"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    VIP = "VIP"


class LoyaltyProgram(str, Enum):
    ALLE = "ALLE"
    ASPIRE = "ASPIRE"


class Product(str, Enum):
    BOTOX = "BOTOX"
    DYSPORT = "DYSPORT"
    JUVEDERM = "JUVEDERM"
    RESTYLANE = "RESTYLANE"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"


class ConsultationStatus(str, Enum):
    DRAFT = "DRAFT"
    EXAM_COMPLETE = "EXAM_COMPLETE"
    VOID = "VOID"


class StandingOrderStatus(str, Enum):
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class TreatmentPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DepositStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"


class SessionStatus(str, Enum):
    BOOKED = "BOOKED"
    COMMITTED = "COMMITTED"
    RESOLVED = "RESOLVED"
    COMPLICATION_OPEN = "COMPLICATION_OPEN"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PhotoKind(str, Enum):
    CONSENT = "CONSENT"
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class ComplicationSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class ComplicationStatus(str, Enum):
    OPEN = "OPEN"
    IN_TOUCHUP = "IN_TOUCHUP"
    RESOLVED = "RESOLVED"


class ResolutionMode(str, Enum):
    REFUND = "REFUND"
    CLINICAL = "CLINICAL"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Provider(TypedDict):
    id: str
    full_name: str
    license_number: str
    role_kind: str
    status: str
    open_complication_count: int
    resolved_complication_count: int
    committed_session_count: int
    created_at: str
    updated_at: str
    version: int


class MembershipPackage(TypedDict):
    id: str
    tier: str
    member_discount_pct: float
    loyalty_program: str
    monthly_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class InjectableLot(TypedDict):
    id: str
    product: str
    lot_number: str
    expiration_date: str
    total_units: int
    reserved_units: int
    consumed_units: int
    remaining_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    membership_id: Optional[str]
    photo_consent_on_file: bool
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    patient_id: str
    program: str
    points_earned: int
    points_redeemed: int
    points_balance: int
    created_at: str
    updated_at: str
    version: int


class Consultation(TypedDict):
    id: str
    patient_id: str
    exam_provider_id: str
    chief_complaint: str
    exam_clock_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    consultation_id: str
    director_provider_id: str
    product: str
    max_units_authorized: int
    valid_until_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    consultation_id: str
    product: str
    planned_sessions: int
    planned_units_per_session: int
    list_price_per_unit_cents: int
    required_deposit_cents: int
    deposit_paid_cents: int
    provisional_series_cost_cents: int
    finalized_series_cost_cents: int
    sessions_committed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    treatment_plan_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentSession(TypedDict):
    id: str
    treatment_plan_id: str
    standing_order_id: str
    injector_provider_id: str
    injectable_lot_id: str
    planned_units: int
    actual_units: Optional[int]
    loyalty_points_redeemed: int
    final_charge_cents: int
    balance_due_cents: int
    points_earned_cents_basis: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplicationCase(TypedDict):
    id: str
    treatment_session_id: str
    injector_provider_id: str
    severity: str
    touchup_rounds: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> immutable event record, only id + created_at (§2.4)
class ConsentPhoto(TypedDict):
    id: str
    patient_id: str
    treatment_session_id: Optional[str]
    kind: str
    signed: bool
    storage_uri: str
    created_at: str
