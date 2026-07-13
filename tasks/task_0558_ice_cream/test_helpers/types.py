"""Domain types: entity TypedDicts, status enums, role enum (Ice Cream Shop API)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    MANAGER = "Manager"
    SHIFT_LEAD = "ShiftLead"
    SCOOPER = "Scooper"
    BAKER = "Baker"


class FlavorStockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    BELOW_PAR = "BELOW_PAR"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class BatchStatus(str, Enum):
    PREP = "PREP"
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    DISCARDED = "DISCARDED"


class WasteType(str, Enum):
    MELT = "MELT"
    SPILLAGE = "SPILLAGE"
    TRIM_SHRINK = "TRIM_SHRINK"
    EXPIRED_DISCARD = "EXPIRED_DISCARD"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    COMMITTED = "COMMITTED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


class PreOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CateringBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class DrawerStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReconciliationStatus(str, Enum):
    PENDING = "PENDING"
    BALANCED = "BALANCED"
    OVER = "OVER"
    SHORT = "SHORT"


# ---- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ----

class Flavor(TypedDict):
    id: str
    name: str
    allergens: List[str]
    is_seasonal: bool
    seasonal_start_utc: Optional[str]
    seasonal_end_utc: Optional[str]
    is_premium: bool
    premium_surcharge_cents_per_scoop: int
    standard_cost_cents_per_ml: float
    par_level_ml: int
    is_active: bool
    total_available_ml: int
    stock_status: str
    created_at: str
    updated_at: str
    version: int


class SizeOption(TypedDict):
    id: str
    code: str
    scoop_count: int
    base_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Topping(TypedDict):
    id: str
    name: str
    price_cents: int
    allergens: List[str]
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    flavor_id: str
    initial_volume_ml: int
    unit_cost_cents_per_ml: float
    produced_at: str
    expiry_at: str
    remaining_volume_ml: int
    reserved_volume_ml: int
    committed_volume_ml: int
    wasted_volume_ml: int
    expected_shrink_ml: int
    actual_shrink_ml: int
    shrink_variance_ml: int
    status: str
    created_at: str
    updated_at: str
    version: int


# WasteEvent: common_fields FALSE -> only id + created_at (no updated_at, no version)
class WasteEvent(TypedDict):
    id: str
    batch_id: str
    waste_type: str
    volume_ml: int
    reason: str
    created_at: str


class LoyaltyAccount(TypedDict):
    id: str
    phone: str
    allergen_restrictions: List[str]
    punches: int
    free_scoop_credits: int
    lifetime_scoops: int
    created_at: str
    updated_at: str
    version: int


class CashDrawerSession(TypedDict):
    id: str
    opening_float_cents: int
    expected_cash_cents: int
    gross_sales_cents: int
    net_sales_cents: int
    counted_cash_cents: Optional[int]
    variance_cents: Optional[int]
    reconciliation_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    drawer_id: str
    loyalty_account_id: Optional[str]
    payment_method: Optional[str]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    tendered_cash_cents: Optional[int]
    change_cents: Optional[int]
    cash_collected_cents: int
    cash_refunded_cents: int
    standard_cogs_cents: int
    actual_cogs_cents: int
    punches_earned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    size_option_id: str
    flavor_id: str
    topping_ids: List[str]
    quantity: int
    scoops: int
    line_price_cents: int
    line_tax_cents: int
    allergen_label: List[str]
    allocations: List[dict]
    standard_cogs_cents: int
    actual_cogs_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PreOrder(TypedDict):
    id: str
    flavor_id: str
    decorating_station_id: str
    customer_name: str
    is_custom: bool
    custom_notes: str
    decorate_start_utc: str
    decorate_end_utc: str
    pickup_utc: str
    quoted_price_cents: int
    deposit_cents: int
    final_price_cents: Optional[int]
    refunded_cents: int
    allergen_label: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringBooking(TypedDict):
    id: str
    event_cart_id: str
    event_start_utc: str
    event_end_utc: str
    requested_items: List[dict]
    estimate_cents: int
    actual_items: List[dict]
    actual_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
