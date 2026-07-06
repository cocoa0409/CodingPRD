"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    STORE_CLERK = "StoreClerk"
    DELIVERY_DRIVER = "DeliveryDriver"
    CUSTOMER = "Customer"


class SkuCategory(str, Enum):
    BALLOON_LATEX = "BALLOON_LATEX"
    BALLOON_FOIL = "BALLOON_FOIL"
    COSTUME = "COSTUME"
    TABLEWARE = "TABLEWARE"
    DECOR = "DECOR"
    PRINT_CUSTOM = "PRINT_CUSTOM"
    HELIUM = "HELIUM"
    SEASONAL_HALLOWEEN = "SEASONAL_HALLOWEEN"


class BundleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    PICKING = "PICKING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class OrderChannel(str, Enum):
    BOPIS = "BOPIS"
    DELIVERY = "DELIVERY"
    IN_STORE = "IN_STORE"


class HeliumTankStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EMPTY = "EMPTY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DeliverySlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RentalContractStatus(str, Enum):
    RESERVED = "RESERVED"
    PICKED_UP = "PICKED_UP"
    RETURNED = "RETURNED"
    LATE_RETURN = "LATE_RETURN"
    DAMAGED = "DAMAGED"


class CustomPrintOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PROOF_SENT = "PROOF_SENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    PRINTING = "PRINTING"
    READY = "READY"
    CANCELLED = "CANCELLED"


class EventBookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FORFEITED = "FORFEITED"


class PayMode(str, Enum):
    DEPOSIT = "DEPOSIT"
    FULL = "FULL"


# common_fields: true — id + created_at + updated_at + version
class Sku(TypedDict, total=False):
    id: str
    sku_code: str
    category: str
    unit_price_cents: int
    theme_tag: Optional[str]
    on_hand_qty: int
    reserved_qty: int
    seasonal_window_start: Optional[str]
    seasonal_window_end: Optional[str]
    is_clearance: bool
    clearance_pct: float
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict, total=False):
    id: str
    bundle_code: str
    theme_tag: str
    bundle_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — id + created_at only
class BundleLine(TypedDict, total=False):
    id: str
    bundle_id: str
    sku_id: str
    qty: int
    created_at: str


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    fulfillment_status: str
    payment_status: str
    channel: str
    pickup_window_start: Optional[str]
    pickup_window_end: Optional[str]
    subtotal_cents: int
    helium_fee_cents: int
    delivery_fee_cents: int
    deposit_cents: int
    grand_total_cents: int
    pickup_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    sku_id: Optional[str]
    bundle_id: Optional[str]
    qty: int
    unit_price_cents_at_capture: int
    line_total_cents: int
    created_at: str


class HeliumOrder(TypedDict, total=False):
    id: str
    order_id: str
    latex_count: int
    foil_count: int
    helium_tank_ids: List[str]
    fill_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class HeliumTank(TypedDict, total=False):
    id: str
    tank_code: str
    capacity_cubic_ft: int
    remaining_cubic_ft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliverySlot(TypedDict, total=False):
    id: str
    window_start: str
    window_end: str
    van_id: str
    setup_included: bool
    order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalContract(TypedDict, total=False):
    id: str
    order_id: str
    sku_id: str
    qty: int
    rental_start: str
    rental_end: str
    deposit_cents: int
    status: str
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomPrintOrder(TypedDict, total=False):
    id: str
    order_id: str
    art_reference: str
    banner_length_ft: int
    status: str
    revision_count: int
    print_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class EventPackage(TypedDict, total=False):
    id: str
    package_code: str
    base_price_cents: int
    deposit_pct: float
    min_lead_days: int
    created_at: str
    updated_at: str
    version: int


class EventBooking(TypedDict, total=False):
    id: str
    order_id: str
    event_package_id: str
    event_date: str
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int
