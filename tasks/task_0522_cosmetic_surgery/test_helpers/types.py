"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    FRONT_DESK_COORDINATOR = "FrontDeskCoordinator"
    SURGEON = "Surgeon"
    BILLING_SPECIALIST = "BillingSpecialist"


class ProcedureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ClearanceTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    MEDICAL = "MEDICAL"


class ConsultationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CONVERTED = "CONVERTED"
    CLOSED = "CLOSED"


class QuotePackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class ClearanceStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class SurgeryBookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FinancingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class ComplicationStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_APPROVED = "REVISION_APPROVED"
    RESOLVED = "RESOLVED"


class Lender(str, Enum):
    CARECREDIT = "CARECREDIT"
    CHERRY = "CHERRY"


class Attribution(str, Enum):
    SURGICAL_ORIGIN = "SURGICAL_ORIGIN"
    PATIENT_FACTOR = "PATIENT_FACTOR"
    UNRELATED = "UNRELATED"


# common_fields: true — id + created_at + updated_at + version
class Procedure(TypedDict):
    id: str
    code: str
    name: str
    surgical_fee_cents: int
    facility_fee_cents: int
    anesthesia_fee_cents: int
    revision_window_days: int
    active: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    age_years: int
    asa_class: int
    bmi: float
    smoker: bool
    prior_complication_count: int
    surgical_risk_score: int
    clearance_tier: str
    created_at: str
    updated_at: str
    version: int


class Consultation(TypedDict):
    id: str
    patient_id: str
    surgeon_user_id: str
    chief_complaint: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QuotePackage(TypedDict):
    id: str
    consultation_id: str
    patient_id: str
    subtotal_cents: int
    discount_pct: float
    total_cents: int
    required_deposit_cents: int
    deposit_paid_cents: int
    financed_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only: id + created_at only (NO updated_at, NO version)
class QuoteLineItem(TypedDict):
    id: str
    quote_package_id: str
    procedure_id: str
    surgical_fee_cents: int
    facility_fee_cents: int
    anesthesia_fee_cents: int
    bundle_total_cents: int
    created_at: str


class ConsentRecord(TypedDict):
    id: str
    quote_package_id: str
    before_photo_ref: str
    photo_consent_signed: bool
    surgical_consent_signed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ClearanceRecord(TypedDict):
    id: str
    patient_id: str
    tier_required: str
    tier_provided: str
    cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SurgeryBooking(TypedDict):
    id: str
    quote_package_id: str
    patient_id: str
    surgeon_user_id: str
    or_room: str
    scheduled_start: str
    scheduled_end: str
    deposit_forfeited_cents: int
    deposit_refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    quote_package_id: str
    lender: str
    requested_amount_cents: int
    approved_amount_cents: int
    merchant_fee_cents: int
    practice_net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplicationCase(TypedDict):
    id: str
    surgery_booking_id: str
    line_item_id: str
    reported_at: str
    attribution: str
    within_revision_window: bool
    revision_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
