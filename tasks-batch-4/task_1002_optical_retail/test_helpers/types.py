"""Domain types for the Optical Retail & Eyewear API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    OPTICIAN_VERIFIER = "OpticianVerifier"
    STORE_ASSOCIATE = "StoreAssociate"
    LAB_TECHNICIAN = "LabTechnician"
    BENEFITS_ADMIN = "BenefitsAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ────────────────────────────────────────────────────────────

class PolicyNetwork(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class StoreStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FrameStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class LensCategory(str, Enum):
    MATERIAL = "MATERIAL"
    COATING = "COATING"


class LensOptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PrescriptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class KitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SHIPPED = "SHIPPED"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"


class KitItemOutcome(str, Enum):
    PENDING = "PENDING"
    KEPT = "KEPT"
    RETURNED = "RETURNED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_LAB = "IN_LAB"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class DeliveryMethod(str, Enum):
    SHIP = "SHIP"
    BOPIS = "BOPIS"


class QuoteVariant(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINAL = "FINAL"


class LabOrderStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PRODUCTION = "IN_PRODUCTION"
    REMAKE_QUEUED = "REMAKE_QUEUED"
    QC_PASSED = "QC_PASSED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED_APPROVED = "ADJUDICATED_APPROVED"
    ADJUDICATED_DENIED = "ADJUDICATED_DENIED"
    REIMBURSED = "REIMBURSED"
    VOID = "VOID"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class WarrantyReason(str, Enum):
    MANUFACTURER_DEFECT = "MANUFACTURER_DEFECT"
    CUSTOMER_DAMAGE = "CUSTOMER_DAMAGE"
    RX_CHANGE = "RX_CHANGE"


# ─── Entity shapes ───────────────────────────────────────────────────────────
# PRD §2.4: every persisted resource carries `id` + `created_at`. All resources
# EXCEPT the try-on kit item additionally carry `updated_at` and `version`.


class InsurancePolicy(TypedDict):
    id: str
    member_id: str
    network: str
    frame_allowance_cents: int
    frame_allowance_remaining_cents: int
    lens_copay_cents: int
    annual_max_cents: int
    annual_reimbursed_cents: int
    oon_reimburse_pct: float
    oon_fee_schedule: Dict[str, int]
    plan_year_start: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    name: str
    status: str
    exam_chairs: int
    buffer_minutes: int
    pickup_capacity_per_day: int
    created_at: str
    updated_at: str
    version: int


class Frame(TypedDict):
    id: str
    sku: str
    name: str
    brand: str
    price_cents: int
    status: str
    tryon_stock: int
    tryon_available: int
    min_pd_mm: float
    max_pd_mm: float
    created_at: str
    updated_at: str
    version: int


class LensOption(TypedDict):
    id: str
    code: str
    category: str
    base_price_cents: int
    material_index: Optional[float]
    incompatible_with: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    dob: str
    insurance_policy_id: Optional[str]
    fsa_balance_cents: int
    lifetime_kit_count: int
    return_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    customer_id: str
    od_sphere: float
    od_cylinder: float
    os_sphere: float
    os_cylinder: float
    pd_mm: float
    prism_diopters: float
    issued_at: str
    expires_at: str
    status: str
    verified_by: Optional[str]
    rejection_reason: Optional[str]
    resubmit_count: int
    created_at: str
    updated_at: str
    version: int


class HomeTryOnKit(TypedDict):
    id: str
    customer_id: str
    ship_date: str
    due_date: str
    status: str
    was_overdue: bool
    item_count: int
    kept_count: int
    late_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class TryOnKitItem(TypedDict):
    """PRD §2.4: a try-on kit item carries ONLY `id` and `created_at` — no
    `updated_at` and no `version`."""

    id: str
    kit_id: str
    frame_id: str
    outcome: str
    created_at: str


class ExamAppointment(TypedDict):
    id: str
    customer_id: str
    store_id: str
    start_at: str
    end_at: str
    status: str
    resulting_prescription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    prescription_id: str
    frame_id: str
    material_option_id: str
    coating_option_ids: List[str]
    store_id: Optional[str]
    exam_appointment_id: Optional[str]
    active_claim_id: Optional[str]
    delivery_method: str
    fulfillment_status: str
    payment_status: str
    lens_upcharge_cents: int
    subtotal_cents: int
    discount_cents: int
    benefit_frame_cents: int
    benefit_lens_cents: int
    benefit_applied_cents: int
    fsa_applied_cents: int
    customer_due_cents: int
    quote_variant: str
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict):
    id: str
    order_id: str
    shipped_to_store_id: Optional[str]
    active_warranty_claim_id: Optional[str]
    status: str
    remake_count: int
    qc_failure_reason: Optional[str]
    is_remake: bool
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    order_id: str
    policy_id: str
    service_lines: List[Dict[str, Any]]
    status: str
    reserved_frame_benefit_cents: int
    allowed_amount_cents: Optional[int]
    approved_amount_cents: int
    reimbursed_amount_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    lab_order_id: str
    customer_id: str
    remake_lab_order_id: Optional[str]
    reason: str
    status: str
    customer_charge_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
