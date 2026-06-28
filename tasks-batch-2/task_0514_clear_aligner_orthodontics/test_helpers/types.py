"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─────────────────────────────────────────────────────────────────────────────
# Roles
# ─────────────────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PATIENT = "Patient"
    CLINICIAN = "Clinician"
    MANUFACTURING_OPS = "ManufacturingOps"
    BILLING_ADMIN = "BillingAdmin"


# ─────────────────────────────────────────────────────────────────────────────
# Status enums
# ─────────────────────────────────────────────────────────────────────────────
class TreatmentCaseStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECLINED = "DECLINED"
    PLAN_APPROVED = "PLAN_APPROVED"
    ACTIVE = "ACTIVE"
    REFINEMENT = "REFINEMENT"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    ELIGIBILITY_DECLINED = "ELIGIBILITY_DECLINED"


class AlignerStepStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    MANUFACTURED = "MANUFACTURED"
    SHIPPED = "SHIPPED"
    VOID = "VOID"


class ShipmentStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TrackingAssessment(str, Enum):
    PENDING = "PENDING"
    ON_TRACK = "ON_TRACK"
    OFF_TRACK = "OFF_TRACK"


class RefinementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class BillingState(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    CANCELLED = "CANCELLED"


class DelinquencyState(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    POSTED = "POSTED"
    LATE = "LATE"
    WAIVED = "WAIVED"


class RetainerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class RefundStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class IntakeChannel(str, Enum):
    IMPRESSION_KIT = "IMPRESSION_KIT"
    IN_OFFICE_SCAN = "IN_OFFICE_SCAN"


class CarrierCode(str, Enum):
    GROUND = "GROUND"
    EXPRESS = "EXPRESS"


class RetainerCadence(str, Enum):
    QUARTERLY = "QUARTERLY"
    SEMIANNUAL = "SEMIANNUAL"


class RefundReason(str, Enum):
    ELIGIBILITY_DECLINE = "ELIGIBILITY_DECLINE"
    PATIENT_CANCEL = "PATIENT_CANCEL"
    GOODWILL = "GOODWILL"


class ClinicianRoleType(str, Enum):
    DENTIST = "DENTIST"
    ORTHODONTIST = "ORTHODONTIST"


# ─────────────────────────────────────────────────────────────────────────────
# Entity TypedDicts
#
# Every persisted resource carries id + created_at. Resources that the contract
# versions carry updated_at + version too; ProgressCheckin is append-only and
# carries ONLY id + created_at.
# ─────────────────────────────────────────────────────────────────────────────
class Patient(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    date_of_birth: str
    is_minor_at_intake: bool
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    full_name: str
    license_state_codes: List[str]
    role_type: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class TreatmentCase(TypedDict):
    id: str
    patient_id: str
    intake_channel: str
    status: str
    assigned_clinician_id: Optional[str]
    list_price_cents: int
    total_contracted_cents: int
    amount_collected_cents: int
    refund_issued_cents: int
    refinement_count: int
    planned_step_count: int
    guardian_consent: bool
    created_at: str
    updated_at: str
    version: int


class IntakeRecord(TypedDict):
    id: str
    case_id: str
    channel: str
    captured_at: str
    kit_tracking_number: Optional[str]
    scan_clinic_state_code: Optional[str]
    quality_score: float
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    case_id: str
    author_clinician_id: str
    revision: int
    status: str
    proposed_step_count: int
    weeks_per_step: int
    discount_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlignerStep(TypedDict):
    id: str
    case_id: str
    step_index: int
    status: str
    supersedes_step_id: Optional[str]
    scheduled_ship_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    step_id: str
    carrier_code: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record: id + created_at ONLY (no updated_at, no version).
class ProgressCheckin(TypedDict):
    id: str
    case_id: str
    reported_step_index: int
    photo_quality_score: float
    tracking_assessment: str
    created_at: str


class RefinementRequest(TypedDict):
    id: str
    case_id: str
    triggering_checkin_id: str
    additional_step_count: int
    status: str
    is_billable: bool
    created_at: str
    updated_at: str
    version: int


class FinancingPlan(TypedDict):
    id: str
    case_id: str
    term_months: int
    down_payment_cents: int
    apr_bps: int
    billing_state: str
    delinquency_state: str
    financed_principal_cents: int
    outstanding_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    financing_plan_id: str
    sequence_no: int
    due_at: str
    amount_cents: int
    principal_portion_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetainerSubscription(TypedDict):
    id: str
    case_id: str
    cadence: str
    per_shipment_fee_cents: int
    status: str
    next_ship_at: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    case_id: str
    reason: str
    status: str
    computed_refund_cents: int
    restocking_fee_cents: int
    created_at: str
    updated_at: str
    version: int
