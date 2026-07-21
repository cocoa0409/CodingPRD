"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §2.4)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SHOWROOM_ASSOCIATE = "ShowroomAssociate"
    FULFILLMENT_COORDINATOR = "FulfillmentCoordinator"
    DESIGNER = "Designer"
    STORE_MANAGER = "StoreManager"


class FixtureCategory(str, Enum):
    CEILING_FAN = "CEILING_FAN"
    CHANDELIER = "CHANDELIER"
    PENDANT = "PENDANT"
    SCONCE = "SCONCE"
    RECESSED = "RECESSED"


class TradeAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class TradeTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    READY = "READY"
    CANCELLED = "CANCELLED"


class DesignConsultStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_REVIEW = "IN_REVIEW"
    REVISION = "REVISION"
    APPROVED = "APPROVED"


class DeliveryJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class InstallReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ReturnReason(str, Enum):
    DAMAGE = "DAMAGE"
    DEFECTIVE = "DEFECTIVE"
    CHANGED_MIND = "CHANGED_MIND"
    WARRANTY = "WARRANTY"


class ReturnRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REFUNDED = "REFUNDED"
    DENIED = "DENIED"


class RebateClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    VOID = "VOID"
    DENIED = "DENIED"


# All entities in this system are mutable and carry the full common quartet
# (id, created_at, updated_at, version) per PRD §2.4.
class TradeAccount(TypedDict):
    id: str
    business_name: str
    contact_email: str
    credit_limit_cents: int
    available_credit_cents: int
    annual_spend_cents: int
    tier: str
    discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FixtureModel(TypedDict):
    id: str
    sku_base: str
    category: str
    base_price_cents: int
    base_wattage: int
    energy_star: bool
    special_order_only: bool
    supplier_lead_days: int
    options: list
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    trade_account_id: Optional[str]
    customer_name: str
    fulfillment_status: str
    payment_status: str
    subtotal_estimate_cents: int
    discount_estimate_cents: int
    total_estimate_cents: int
    subtotal_final_cents: Optional[int]
    discount_final_cents: Optional[int]
    total_final_cents: Optional[int]
    committed_credit_cents: int
    amount_paid_cents: int
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    fixture_model_id: str
    selected_option_ids: list
    configured_sku: str
    quantity: int
    unit_price_cents: int
    is_special_order: bool
    line_status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    supplier_lead_days: int
    status: str
    confirmed_at: Optional[str]
    estimated_ready_date: Optional[str]
    actual_ready_date: Optional[str]
    variance_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DesignConsult(TypedDict):
    id: str
    trade_account_id: str
    order_id: Optional[str]
    room_type: str
    fee_cents: int
    status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Installer(TypedDict):
    id: str
    name: str
    service_area: str
    daily_capacity: int
    active_referral_count: int
    created_at: str
    updated_at: str
    version: int


class InstallReferral(TypedDict):
    id: str
    order_id: str
    installer_id: str
    delivery_job_id: str
    appointment_start: Optional[str]
    appointment_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTruck(TypedDict):
    id: str
    name: str
    capacity_units: int
    created_at: str
    updated_at: str
    version: int


class DeliveryJob(TypedDict):
    id: str
    order_id: str
    delivery_truck_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    reason: str
    status: str
    restocking_fee_cents: Optional[int]
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RebateProgram(TypedDict):
    id: str
    name: str
    rebate_rate: float
    wattage_ceiling: int
    budget_total_cents: int
    budget_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class RebateClaim(TypedDict):
    id: str
    order_id: str
    rebate_program_id: str
    claimed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
