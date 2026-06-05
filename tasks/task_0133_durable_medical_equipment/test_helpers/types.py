"""Domain types: entity TypedDicts, status enums, role enum for the DME API."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPLIER_USER = "SupplierUser"
    PHYSICIAN_USER = "PhysicianUser"
    PAYER_REVIEWER = "PayerReviewer"


# ─── Status enums ─────────────────────────────────────
class DMEOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    ACTIVE = "ACTIVE"
    CONVERTED_TO_PURCHASE = "CONVERTED_TO_PURCHASE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CMNStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class PriorAuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RentalBillingCycleStatus(str, Enum):
    BILLED = "BILLED"
    PAID = "PAID"
    RECOUPED = "RECOUPED"


class ClaimLineStatus(str, Enum):
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ClaimLineType(str, Enum):
    RENTAL_MONTH = "RENTAL_MONTH"
    PURCHASE = "PURCHASE"
    RECOUPMENT = "RECOUPMENT"


class CPAPResupplyOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SHIPPED = "SHIPPED"
    DENIED = "DENIED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


# ─── Field-value enums ────────────────────────────────
class BillingCategory(str, Enum):
    CAPPED_RENTAL = "CAPPED_RENTAL"
    INEXPENSIVE_ROUTINE = "INEXPENSIVE_ROUTINE"
    PURCHASE_ONLY = "PURCHASE_ONLY"
    OXYGEN = "OXYGEN"


class AcquisitionType(str, Enum):
    RENTAL = "RENTAL"
    PURCHASE = "PURCHASE"


class Modifier(str, Enum):
    NONE = "NONE"
    NU = "NU"
    KX = "KX"


class SupplyKind(str, Enum):
    MASK = "MASK"
    TUBING = "TUBING"
    FILTER = "FILTER"
    HEADGEAR = "HEADGEAR"


class AuditReasonCode(str, Enum):
    NO_VALID_CMN = "NO_VALID_CMN"
    NO_PROOF_OF_DELIVERY = "NO_PROOF_OF_DELIVERY"
    OVERBILLED_PAST_CAP = "OVERBILLED_PAST_CAP"
    NO_PRIOR_AUTH = "NO_PRIOR_AUTH"


# ─── Entity TypedDicts (all carry common_fields: true) ─
class Patient(TypedDict):
    id: str
    full_name: str
    medicare_id: str
    date_of_birth: str
    address_state: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    ptan: str
    accreditation_active: bool
    created_at: str
    updated_at: str
    version: int


class HCPCSItem(TypedDict):
    id: str
    hcpcs_code: str
    description: str
    billing_category: str
    purchase_price_cents: int
    monthly_rental_cents: int
    requires_cmn: bool
    requires_prior_auth: bool
    is_cpap: bool
    created_at: str
    updated_at: str
    version: int


class DMEOrder(TypedDict):
    id: str
    patient_id: str
    supplier_id: str
    hcpcs_item_id: str
    acquisition_type: str
    modifier: str
    ordered_at_utc: str
    rental_months_billed: int
    cap_reached: bool
    total_allowed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CMN(TypedDict):
    id: str
    order_id: str
    physician_npi: str
    length_of_need_months: int
    signed_date: str
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    order_id: str
    payer_reference: str
    decision_reason: Optional[str]
    status: str
    expires_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    order_id: str
    scheduled_for_utc: str
    delivered_at_utc: Optional[str]
    pod_signature_name: Optional[str]
    pod_received: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalBillingCycle(TypedDict):
    id: str
    order_id: str
    cycle_index: int
    period_start_utc: str
    period_end_utc: str
    billed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    order_id: str
    rental_cycle_id: Optional[str]
    audit_id: Optional[str]
    line_type: str
    allowed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CPAPResupplyOrder(TypedDict):
    id: str
    order_id: str
    supply_kind: str
    requested_at_utc: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    order_id: str
    reason_code: str
    recouped_total_cents: int
    recouped_cycle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
