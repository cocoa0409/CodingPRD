"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class PlantLightTag(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    BRIGHT_INDIRECT = "BRIGHT_INDIRECT"
    DIRECT = "DIRECT"


class PlantCareTag(str, Enum):
    EASY = "EASY"
    MODERATE = "MODERATE"
    EXPERT = "EXPERT"


class PlantWeightClass(str, Enum):
    LIGHT = "LIGHT"
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class DeliveryZone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"


class StockUnitHealth(str, Enum):
    HEALTHY = "HEALTHY"
    RECOVERING = "RECOVERING"
    DECLINING = "DECLINING"
    DEAD = "DEAD"


class StockUnitSaleStatus(str, Enum):
    FOR_SALE = "FOR_SALE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    SHRINK = "SHRINK"
    RETURNED = "RETURNED"


class ShrinkReason(str, Enum):
    NONE = "NONE"
    MORTALITY = "MORTALITY"
    DAMAGED = "DAMAGED"
    EXPIRED_HOLD = "EXPIRED_HOLD"
    WARRANTY_RETURN = "WARRANTY_RETURN"


class CareLogEntryType(str, Enum):
    WATER = "WATER"
    LIGHT_CHECK = "LIGHT_CHECK"
    PRUNE = "PRUNE"
    REPOT = "REPOT"
    OBSERVATION = "OBSERVATION"
    SHRINK_DECLARE = "SHRINK_DECLARE"


class OrderFulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderLineRefundStatus(str, Enum):
    NONE = "NONE"
    PENDING_REVIEW = "PENDING_REVIEW"
    REFUNDED = "REFUNDED"
    DENIED = "DENIED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    MISSING_STOCK = "MISSING_STOCK"


class SubscriptionPlanTier(str, Enum):
    STARTER = "STARTER"
    CLASSIC = "CLASSIC"
    CURATOR = "CURATOR"


class CareReminderStatus(str, Enum):
    PENDING = "PENDING"
    DUE = "DUE"
    DISMISSED = "DISMISSED"


class WorkshopTopic(str, Enum):
    REPOTTING = "REPOTTING"
    LIGHT_101 = "LIGHT_101"
    PROPAGATION = "PROPAGATION"
    PEST_CONTROL = "PEST_CONTROL"


class WorkshopRoom(str, Enum):
    STUDIO_A = "STUDIO_A"
    STUDIO_B = "STUDIO_B"


class WorkshopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkshopRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class WarrantyClaimReason(str, Enum):
    MORTALITY = "MORTALITY"
    DAMAGED = "DAMAGED"
    MISDELIVERY = "MISDELIVERY"
    OTHER = "OTHER"


class SpecialOrderServiceType(str, Enum):
    PROCUREMENT = "PROCUREMENT"
    REPOTTING = "REPOTTING"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    RE_QUOTED = "RE_QUOTED"
    CUSTOMER_APPROVED = "CUSTOMER_APPROVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class LoyaltyLedgerReason(str, Enum):
    ACCRUAL_PROVISIONAL = "ACCRUAL_PROVISIONAL"
    ACCRUAL_FINAL_DELTA = "ACCRUAL_FINAL_DELTA"
    REVERSAL = "REVERSAL"
    REDEMPTION = "REDEMPTION"
    MANUAL_ADJUST = "MANUAL_ADJUST"


class UserRole(str, Enum):
    Anonymous = "Anonymous"
    Customer = "Customer"
    ShopStaff = "ShopStaff"
    Horticulturist = "Horticulturist"
    DeliveryDriver = "DeliveryDriver"
    Manager = "Manager"


# --- Entity TypedDicts ---
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at  (append-only entities: CareLogEntry, LoyaltyLedger, OrderLine)


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    delivery_zone: str
    address_line: str
    loyalty_tier: str
    points_balance: int
    lifetime_points_earned: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Plant(TypedDict):
    id: str
    name: str
    light_tag: str
    care_tag: str
    weight_class: str
    unit_price_cents: int
    warranty_days: int
    available_count: int
    created_at: str
    updated_at: str
    version: int


class StockUnit(TypedDict):
    id: str
    plant_id: str
    acquisition_date: str
    health_status: str
    sale_status: str
    shrink_reason: str
    created_at: str
    updated_at: str
    version: int


class CareLogEntry(TypedDict):
    id: str
    stock_unit_id: str
    entry_type: str
    actor_role: str
    note: str
    entered_at: str
    created_at: str
    # append-only: NO updated_at, NO version


class DeliveryDriver(TypedDict):
    id: str
    name: str
    daily_capacity_minutes: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    fulfillment_status: str
    payment_status: str
    delivery_zone: str
    gift_flag: bool
    applied_redemption_cents: int
    subtotal_cents: int
    delivery_fee_cents: int
    total_cents: int
    points_provisional: int
    points_finalized: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    plant_id: str
    stock_unit_id: str
    qty: int
    unit_price_cents: int
    line_subtotal_cents: int
    refund_status: str
    refund_amount_cents: int
    created_at: str
    # append-only: NO updated_at, NO version


class DeliveryAssignment(TypedDict):
    id: str
    order_id: str
    driver_id: str
    window_start_at: str
    window_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    plan_tier: str
    care_tag_preference: str
    light_tag_preference: str
    status: str
    next_fulfillment_at: str
    monthly_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class CareReminder(TypedDict):
    id: str
    customer_id: str
    subscription_id: Optional[str]
    due_at: str
    message: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Workshop(TypedDict):
    id: str
    title: str
    topic: str
    room_id: str
    start_at: str
    end_at: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkshopRegistration(TypedDict):
    id: str
    workshop_id: str
    customer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    orderline_id: str
    customer_id: str
    reason: str
    submitted_at: str
    status: str
    refund_amount_cents_provisional: int
    refund_amount_cents_final: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    service_type: str
    sku_description: str
    status: str
    quoted_price_cents: int
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class LoyaltyLedger(TypedDict):
    id: str
    customer_id: str
    order_id: Optional[str]
    reason: str
    delta_points: int
    recorded_at: str
    created_at: str
    # append-only: NO updated_at, NO version
