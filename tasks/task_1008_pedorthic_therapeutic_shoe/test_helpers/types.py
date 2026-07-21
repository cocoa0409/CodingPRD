"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------- Roles ---------------------------
class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    FITTER = "Fitter"
    BILLING_SPECIALIST = "BillingSpecialist"
    CUSTOMER = "Customer"


# --------------------------- Status enums ---------------------------
class ProductCategory(str, Enum):
    THERAPEUTIC = "THERAPEUTIC"
    DIABETIC = "DIABETIC"
    ORTHOTIC = "ORTHOTIC"
    REGULAR = "REGULAR"
    INSERT = "INSERT"


class InventoryStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DISCONTINUED = "DISCONTINUED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AppointmentType(str, Enum):
    FITTING = "FITTING"
    GAIT = "GAIT"
    DIABETIC_FITTING = "DIABETIC_FITTING"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class SaleLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    EXCHANGED = "EXCHANGED"


class CertificationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    SUPERSEDED = "SUPERSEDED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class ReturnType(str, Enum):
    RETURN = "RETURN"
    EXCHANGE = "EXCHANGE"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"
    EXCHANGED = "EXCHANGED"


class SpecialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class LedgerReason(str, Enum):
    EARN = "EARN"
    REVERSAL = "REVERSAL"
    REDEEM = "REDEEM"
    ADJUST = "ADJUST"


# --------------------------- Entity TypedDicts ---------------------------
# common_fields: true -> id + created_at + updated_at + version
class Product(TypedDict, total=False):
    id: str
    name: str
    brand: str
    category: str
    base_price_cents: int
    medicare_allowable_cents: int
    hcpcs_code: Optional[str]
    is_recalled: bool
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict, total=False):
    id: str
    product_id: str
    size: float
    width: str
    lot_number: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    medicare_beneficiary_id: Optional[str]
    is_pediatric: bool
    loyalty_points_balance: int
    loyalty_tier: str
    medicare_deductible_remaining_cents: int
    medicare_pairs_claimed_ytd: int
    medicare_inserts_claimed_ytd: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> ONLY id + created_at (immutable audit record)
class FootMeasurement(TypedDict, total=False):
    id: str
    customer_id: str
    measured_at: str
    foot_length_mm_left: float
    foot_length_mm_right: float
    foot_width_mm_left: float
    foot_width_mm_right: float
    recommended_mondo_mm: int
    length_change_mm_from_prior: int
    created_at: str


class Fitter(TypedDict, total=False):
    id: str
    full_name: str
    credential: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GaitLab(TypedDict, total=False):
    id: str
    name: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    customer_id: str
    fitter_id: str
    gait_lab_id: Optional[str]
    appointment_type: str
    start_time: str
    end_time: str
    status: str
    recommended_mondo_mm: Optional[int]
    recommended_width: Optional[str]
    gait_findings: Optional[str]
    recommended_orthotic: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict, total=False):
    id: str
    customer_id: str
    fitter_id: str
    appointment_id: Optional[str]
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    loyalty_tier_at_fulfill: Optional[str]
    loyalty_points_earned: int
    created_at: str
    updated_at: str
    version: int


class SaleLine(TypedDict, total=False):
    id: str
    sale_id: str
    inventory_item_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    requires_medicare: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    customer_id: str
    certifying_physician_npi: str
    prescribing_practitioner_npi: str
    statement_date: str
    in_person_visit_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicareClaim(TypedDict, total=False):
    id: str
    customer_id: str
    sale_id: str
    certification_id: str
    hcpcs_code: str
    billed_amount_cents: int
    calendar_year: Optional[int]
    allowed_amount_cents: Optional[int]
    provisional_reimbursement_cents: Optional[int]
    deductible_applied_cents: int
    medicare_paid_cents: int
    patient_responsibility_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    sale_id: str
    sale_line_id: str
    replacement_inventory_item_id: Optional[str]
    return_type: str
    reason: Optional[str]
    refund_amount_cents: int
    restocking_fee_cents: int
    price_difference_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict, total=False):
    id: str
    customer_id: str
    product_id: str
    fulfilled_inventory_item_id: Optional[str]
    requested_size: float
    requested_width: str
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict, total=False):
    id: str
    product_id: str
    lot_number: Optional[str]
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> ONLY id + created_at (immutable audit record)
class LoyaltyLedgerEntry(TypedDict, total=False):
    id: str
    customer_id: str
    sale_id: Optional[str]
    points_delta: int
    reason: str
    created_at: str
