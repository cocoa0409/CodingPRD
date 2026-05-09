"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    GROUP_LEADER = "GroupLeader"
    CUSTOMER = "Customer"
    SUPPLIER = "Supplier"
    PICKUP_OPERATOR = "PickupOperator"
    CUSTOMER_SERVICE = "CustomerService"


class CommunityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class GroupLeaderStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RISK_HOLD = "RISK_HOLD"
    BLOCKED = "BLOCKED"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WarehouseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class FlashCampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXHAUSTED = "EXHAUSTED"


class GroupBuyCampaignStatus(str, Enum):
    FORMING = "FORMING"
    EXTENDED = "EXTENDED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class OrderPaymentStatus(str, Enum):
    PENDING_PAY = "PENDING_PAY"
    PAID = "PAID"
    SETTLED = "SETTLED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    NOT_PLANNED = "NOT_PLANNED"
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    AT_PICKUP = "AT_PICKUP"
    PICKED_UP = "PICKED_UP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CampaignKind(str, Enum):
    GROUP_BUY = "GROUP_BUY"
    FLASH = "FLASH"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    AT_PICKUP = "AT_PICKUP"
    MIS_PICK = "MIS_PICK"
    RECONCILED = "RECONCILED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PickupPointStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ConsolidationBatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AfterSalesCaseType(str, Enum):
    REFUND_ONLY = "REFUND_ONLY"
    RETURN_AND_REFUND = "RETURN_AND_REFUND"
    PARTIAL_COMPENSATION = "PARTIAL_COMPENSATION"


class AfterSalesCaseStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    ARBITRATION = "ARBITRATION"
    RESOLVED_REFUND_ONLY = "RESOLVED_REFUND_ONLY"
    RESOLVED_RETURN_REFUND = "RESOLVED_RETURN_REFUND"
    RESOLVED_PARTIAL_COMPENSATION = "RESOLVED_PARTIAL_COMPENSATION"
    REJECTED = "REJECTED"


class CommissionEntryStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    PENDING_CLAWBACK = "PENDING_CLAWBACK"
    CLAWED_BACK = "CLAWED_BACK"


class CommissionLeaderRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    UPSTREAM = "UPSTREAM"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MATURED = "MATURED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class RiskAlertType(str, Enum):
    BOT_ORDER = "BOT_ORDER"
    FAKE_GROUP_BUY = "FAKE_GROUP_BUY"
    LEADER_SUPPLIER_COLLUSION = "LEADER_SUPPLIER_COLLUSION"


class RiskAlertTargetKind(str, Enum):
    CUSTOMER = "CUSTOMER"
    GROUP_LEADER = "GROUP_LEADER"
    SUPPLIER = "SUPPLIER"
    ORDER = "ORDER"


class RiskAlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskAlertStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


# common_fields: true entities -> id, created_at, updated_at, version
class Community(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    status: str
    timezone_offset_minutes: int
    created_at: str
    updated_at: str
    version: int


class GroupLeader(TypedDict, total=False):
    id: str
    community_id: str
    parent_leader_id: Optional[str]
    tier: int
    display_name: str
    status: str
    chronic_risk_score: float
    acute_risk_score: float
    collusion_audit_count: int
    lifetime_settled_orders: int
    created_period_index: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    community_id: str
    display_name: str
    status: str
    lifetime_completed_orders: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    supplier_id: str
    name: str
    region_code: str
    cold_chain_capable: bool
    handling_periods: int
    cold_handling_periods: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FlashCampaign(TypedDict, total=False):
    id: str
    supplier_id: str
    sku: str
    cold_chain_required: bool
    unit_price_cents: int
    tier_caps: list
    total_stock: int
    locked_units: int
    allocated_units: int
    remaining_units: int
    opens_at_period: int
    closes_at_period: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupBuyCampaign(TypedDict, total=False):
    id: str
    leader_id: str
    community_id: str
    cross_community_partner_leader_ids: list
    supplier_id: str
    sku: str
    cold_chain_required: bool
    unit_price_cents: int
    discount_tiers: list
    opens_at_period: int
    deadline_period: int
    participant_count: int
    settled_tier_index: Optional[int]
    settled_discount_basis_points: Optional[int]
    status: str
    extension_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    campaign_kind: str
    campaign_id: str
    flash_granted_units: Optional[int]
    customer_id: str
    line_items: list
    subtotal_cents: int
    provisional_discount_basis_points: int
    provisional_total_cents: int
    settled_total_cents: int
    refunded_amount_cents: int
    payment_status: str
    fulfillment_status: str
    created_period_index: int
    paid_period_index: Optional[int]
    created_seq: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    warehouse_id: str
    pickup_point_id: str
    line_units: list
    cold_chain_segment: bool
    dispatched_period_index: Optional[int]
    predicted_eta_period_index: Optional[int]
    actual_delivered_period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupPoint(TypedDict, total=False):
    id: str
    community_id: str
    name: str
    capacity_packages: int
    cold_storage_capable: bool
    held_package_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at
class ConsolidationBatch(TypedDict, total=False):
    id: str
    pickup_point_id: str
    created_at: str
    window_start_period: int
    window_end_period: int
    shipment_ids: list
    status: str


class AfterSalesCase(TypedDict, total=False):
    id: str
    order_id: str
    case_type: str
    requested_amount_cents: int
    status: str
    evidence_round: int
    resolved_amount_cents: int
    filed_period_index: int
    created_at: str
    updated_at: str
    version: int


class CommissionEntry(TypedDict, total=False):
    id: str
    leader_id: str
    order_id: str
    leader_role: str
    gross_rebate_cents: int
    tax_withholding_cents: int
    net_rebate_cents: int
    payout_target_period_index: int
    status: str
    payout_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    leader_id: str
    target_period_index: int
    bundled_entry_ids: list
    total_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at
class RiskAlert(TypedDict, total=False):
    id: str
    created_at: str
    created_period_index: int
    alert_type: str
    target_kind: str
    target_id: str
    supporting_supplier_id: Optional[str]
    severity: str
    status: str


class PickupPointSummary(TypedDict, total=False):
    held_package_count: int
    capacity_packages: int
    load_factor: float
    load_state: str
