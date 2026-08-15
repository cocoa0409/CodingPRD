"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ORDERING_CLOSED = "ORDERING_CLOSED"
    SUPPLIER_ORDERED = "SUPPLIER_ORDERED"
    DELIVERED = "DELIVERED"
    SORTED = "SORTED"
    DISTRIBUTION_COMPLETE = "DISTRIBUTION_COMPLETE"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class SellerStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PaymentStatusOfOrder(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    SORTED = "SORTED"
    DISTRIBUTED = "DISTRIBUTED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    RETURNED = "RETURNED"


class PaymentStatus(str, Enum):
    RECORDED = "RECORDED"
    CLEARED = "CLEARED"
    BOUNCED = "BOUNCED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CHECK = "CHECK"
    CARD = "CARD"


class SupplierOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DistributionEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SortTicketStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    SHORT = "SHORT"


class PickupAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    RESOLVED_REPLACEMENT = "RESOLVED_REPLACEMENT"
    RESOLVED_REFUND = "RESOLVED_REFUND"


class ClaimType(str, Enum):
    MISSING = "MISSING"
    DAMAGED = "DAMAGED"


class ClaimResolution(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    REFUND = "REFUND"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED_RESTOCKED = "RECEIVED_RESTOCKED"
    RECEIVED_WRITTEN_OFF = "RECEIVED_WRITTEN_OFF"


class ReturnReason(str, Enum):
    UNSOLD = "UNSOLD"
    DEFECTIVE = "DEFECTIVE"
    WRONG_ITEM = "WRONG_ITEM"
    FAMILY_CHANGED_MIND = "FAMILY_CHANGED_MIND"


class ReturnDisposition(str, Enum):
    RESTOCKABLE = "RESTOCKABLE"
    DAMAGED_WRITE_OFF = "DAMAGED_WRITE_OFF"


class PrizeTierType(str, Enum):
    UNITS_SOLD = "UNITS_SOLD"
    REVENUE_CENTS = "REVENUE_CENTS"
    ORDERS_COUNT = "ORDERS_COUNT"


class PrizeAwardStatus(str, Enum):
    QUEUED = "QUEUED"
    AWARDED = "AWARDED"
    FULFILLED = "FULFILLED"
    FORFEITED = "FORFEITED"
    EXPIRED = "EXPIRED"


class LedgerEntryType(str, Enum):
    PROVISIONAL_CREDIT = "PROVISIONAL_CREDIT"
    SALE_REVERSAL_DEBIT = "SALE_REVERSAL_DEBIT"
    BOUNCE_FEE_DEBIT = "BOUNCE_FEE_DEBIT"
    RETURN_DEBIT = "RETURN_DEBIT"
    CLAIM_LOSS_DEBIT = "CLAIM_LOSS_DEBIT"
    PRIZE_COST_DEBIT = "PRIZE_COST_DEBIT"
    PRIZE_COST_REVERSAL = "PRIZE_COST_REVERSAL"
    FINAL_TRUE_UP_CREDIT = "FINAL_TRUE_UP_CREDIT"
    FINAL_TRUE_UP_DEBIT = "FINAL_TRUE_UP_DEBIT"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class LedgerReferenceType(str, Enum):
    ORDER = "ORDER"
    PAYMENT = "PAYMENT"
    RETURN_REQUEST = "RETURN_REQUEST"
    CLAIM = "CLAIM"
    PRIZE_AWARD = "PRIZE_AWARD"
    CAMPAIGN = "CAMPAIGN"


class UserRole(str, Enum):
    FUNDRAISER_ADMIN = "FundraiserAdmin"
    GROUP_COORDINATOR = "GroupCoordinator"
    TREASURER = "Treasurer"
    SUPPLIER_REP = "SupplierRep"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every lifecycle resource carries id/created_at/
# updated_at/version; ProceedsLedgerEntry is append-only and carries only
# id + created_at from the common set.
# ---------------------------------------------------------------------------

class Campaign(TypedDict, total=False):
    id: str
    name: str
    school_name: str
    order_window_start: str
    order_window_end: str
    expected_delivery_date: str
    default_profit_share_bps: int
    status: str
    distribution_completed_at: Optional[str]
    gross_sales_cents: int
    family_credits_cents: int
    estimated_supplier_cost_cents: int
    actual_supplier_cost_cents: int
    general_fund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StudentGroup(TypedDict, total=False):
    id: str
    campaign_id: str
    name: str
    teacher_name: Optional[str]
    provisional_proceeds_cents: int
    proceeds_balance_cents: int
    final_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    campaign_id: str
    name: str
    sku: str
    unit_price_cents: int
    supplier_unit_cost_cents: int
    case_pack_size: int
    profit_share_bps: int
    per_seller_limit: Optional[int]
    returnable: bool
    status: str
    delivered_units: int
    distributed_units: int
    restocked_units: int
    written_off_units: int
    lost_units: int
    surplus_units: int
    created_at: str
    updated_at: str
    version: int


class IncentivePrize(TypedDict, total=False):
    id: str
    campaign_id: str
    name: str
    tier_type: str
    threshold_value: int
    prize_cost_cents: int
    stock_quantity: int
    remaining_quantity: int
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict, total=False):
    id: str
    group_id: str
    campaign_id: str
    display_name: str
    status: str
    units_sold: int
    revenue_cents: int
    orders_count: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    seller_id: str
    campaign_id: str
    group_id: str
    family_contact_name: str
    status: str
    payment_status: str
    fulfillment_status: str
    total_cents: int
    cleared_cents: int
    provisional_credit_cents: int
    submitted_at: Optional[str]
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    unit_cost_cents: int
    line_total_cents: int
    returned_qty: int
    claim_resolved_refund_qty: int
    sort_shortage_qty: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    order_id: str
    amount_cents: int
    method: str
    external_ref: Optional[str]
    status: str
    recorded_by_user_id: str
    refunded_amount_cents: int
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplierOrder(TypedDict, total=False):
    id: str
    campaign_id: str
    status: str
    submitted_by_user_id: Optional[str]
    acknowledged_by_user_id: Optional[str]
    delivered_by_user_id: Optional[str]
    confirmed_delivery_date: Optional[str]
    actual_delivery_date: Optional[str]
    estimated_cost_cents: int
    actual_cost_cents: int
    total_ordered_units: int
    created_at: str
    updated_at: str
    version: int


class SupplierOrderLine(TypedDict, total=False):
    id: str
    supplier_order_id: str
    product_id: str
    requested_units: int
    case_pack_size: int
    ordered_cases: int
    ordered_units: int
    unit_cost_estimated_cents: int
    unit_cost_actual_cents: Optional[int]
    delivered_units: Optional[int]
    shortage_units: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DistributionEvent(TypedDict, total=False):
    id: str
    campaign_id: str
    venue: str
    window_start: str
    window_end: str
    slot_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SortTicket(TypedDict, total=False):
    id: str
    campaign_id: str
    seller_id: str
    product_id: str
    distribution_event_id: Optional[str]
    expected_qty: int
    verified_qty: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupAppointment(TypedDict, total=False):
    id: str
    distribution_event_id: str
    order_id: str
    slot_start: str
    slot_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationClaim(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: str
    campaign_id: str
    claim_type: str
    quantity: int
    note: Optional[str]
    status: str
    reported_by_user_id: str
    reviewed_by_user_id: Optional[str]
    resolution: Optional[str]
    credit_cents: Optional[int]
    supersedes_claim_id: Optional[str]
    auto_generated: bool
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    seller_id: str
    order_id: str
    order_line_id: str
    campaign_id: str
    quantity: int
    reason: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    refund_cents: Optional[int]
    restocking_fee_cents: Optional[int]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class PrizeAward(TypedDict, total=False):
    id: str
    seller_id: str
    prize_id: str
    campaign_id: str
    status: str
    qualifying_metric_value: int
    qualified_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only: carries ONLY id + created_at from the common set — no
# updated_at, no version.
class ProceedsLedgerEntry(TypedDict, total=False):
    id: str
    group_id: str
    campaign_id: str
    entry_type: str
    amount_cents: int
    reference_type: Optional[str]
    reference_id: Optional[str]
    seq: int
    balance_after_cents: int
    memo: Optional[str]
    created_at: str
