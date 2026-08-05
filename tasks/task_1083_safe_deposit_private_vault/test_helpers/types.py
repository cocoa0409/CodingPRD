"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    VAULT_ADMIN = "VaultAdmin"
    BILLING_CLERK = "BillingClerk"
    VAULT_OFFICER = "VaultOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RENTER = "Renter"
    ANY = "Any"


class BranchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BoxStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    RENTED = "RENTED"
    DELINQUENT = "DELINQUENT"
    DRILL_PENDING = "DRILL_PENDING"
    DRILLED = "DRILLED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class KycStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RenterStanding(str, Enum):
    GOOD = "GOOD"
    FROZEN = "FROZEN"


class RentalStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"
    SURRENDER_PENDING = "SURRENDER_PENDING"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class AccessGrantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXERCISED = "EXERCISED"


class AccessAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class InventoryItemStatus(str, Enum):
    DECLARED = "DECLARED"
    APPRAISED = "APPRAISED"
    INSURED = "INSURED"
    RELEASED = "RELEASED"


class DrillingOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    DRILLED = "DRILLED"
    CANCELLED = "CANCELLED"


class ComplianceCaseStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"
    CLOSED = "CLOSED"


# --- Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ---

class Branch(TypedDict):
    id: str
    name: str
    code: str
    viewing_room_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoxType(TypedDict):
    id: str
    size_class: str
    annual_rate_cents: int
    height_mm: int
    width_mm: int
    depth_mm: int
    created_at: str
    updated_at: str
    version: int


class Box(TypedDict):
    id: str
    branch_id: str
    box_type_id: str
    box_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Renter(TypedDict):
    id: str
    full_name: str
    email: str
    gov_id_ref: str
    date_of_birth: str
    kyc_status: str
    standing: str
    is_deceased: bool
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict):
    id: str
    box_id: str
    renter_id: str
    plan_term_months: int
    annual_rate_cents: int
    autopay_enabled: bool
    autopay_source_ref: Optional[str]
    insurance_rider_enabled: bool
    declared_contents_value_cents: int
    start_date: Optional[str]
    balance_due_cents: int
    paid_through_date: Optional[str]
    delinquent_since: Optional[str]
    surrender_requested_at: Optional[str]
    provisional_refund_cents: Optional[int]
    final_refund_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    rental_id: str
    period_start: str
    period_end: str
    base_rent_cents: int
    insurance_rider_cents: int
    precious_metal_surcharge_cents: int
    late_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    due_date: str
    issued_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    rental_id: str
    invoice_id: Optional[str]
    amount_cents: int
    method: str
    applied_cents: int
    cleared_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict):
    id: str
    rental_id: str
    grantee_renter_id: Optional[str]
    grant_type: str
    grantee_name: str
    grantee_gov_id_ref: Optional[str]
    dual_control_required: bool
    requires_death_certificate: bool
    death_certificate_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessAppointment(TypedDict):
    id: str
    box_id: str
    rental_id: str
    branch_id: str
    grant_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → append-only, only id + created_at
class AccessEvent(TypedDict):
    id: str
    appointment_id: str
    box_id: str
    rental_id: str
    event_type: str
    occurred_at: str
    primary_accessor_ref: str
    dual_control_officer_ref: str
    witness_count: int
    created_at: str


class InventoryItem(TypedDict):
    id: str
    rental_id: str
    description: str
    category: str
    metal_type: Optional[str]
    weight_grams: Optional[float]
    purity: Optional[float]
    declared_value_cents: int
    appraised_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DrillingOrder(TypedDict):
    id: str
    box_id: str
    rental_id: str
    reason: str
    requested_by_ref: str
    approved_by_ref: Optional[str]
    scheduled_at: Optional[str]
    drilled_at: Optional[str]
    drilling_fee_cents: int
    proceeds_cents: int
    proceeds_to_arrears_cents: Optional[int]
    proceeds_to_drilling_cents: Optional[int]
    proceeds_to_admin_cents: Optional[int]
    proceeds_to_escrow_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict):
    id: str
    renter_id: str
    rental_id: Optional[str]
    case_type: str
    severity: str
    opened_on: str
    resolved_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
