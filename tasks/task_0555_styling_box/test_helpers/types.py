"""Domain types: entity TypedDicts, status enums, role enum for the Styling Box API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------- Enums
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CLIENT = "Client"
    STYLIST = "Stylist"
    OPS_ADMIN = "OpsAdmin"


class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class Cadence(str, Enum):
    EVERY_2_WEEKS = "EVERY_2_WEEKS"
    MONTHLY = "MONTHLY"
    EVERY_2_MONTHS = "EVERY_2_MONTHS"
    QUARTERLY = "QUARTERLY"


class RegionCode(str, Enum):
    CA = "CA"
    NY = "NY"
    OR = "OR"


class PriceTier(str, Enum):
    BUDGET = "BUDGET"
    MID = "MID"
    PREMIUM = "PREMIUM"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class Category(str, Enum):
    TOP = "TOP"
    BOTTOM = "BOTTOM"
    SHOE = "SHOE"
    ACCESSORY = "ACCESSORY"


class StylistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FixStatus(str, Enum):
    REQUESTED = "REQUESTED"
    STYLING = "STYLING"
    PREVIEW = "PREVIEW"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CHECKED_OUT = "CHECKED_OUT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FixItemStatus(str, Enum):
    SELECTED = "SELECTED"
    KEPT = "KEPT"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class ReturnShipmentStatus(str, Enum):
    LABEL_ISSUED = "LABEL_ISSUED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"


class FeedbackRating(str, Enum):
    TOO_SMALL = "TOO_SMALL"
    SLIGHTLY_SMALL = "SLIGHTLY_SMALL"
    PERFECT = "PERFECT"
    SLIGHTLY_LARGE = "SLIGHTLY_LARGE"
    TOO_LARGE = "TOO_LARGE"


class PurchaseStatus(str, Enum):
    PLACED = "PLACED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------- Entity TypedDicts (mutable set)
class Client(TypedDict):
    id: str
    email: str
    full_name: str
    region_code: str
    cadence: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StyleProfile(TypedDict):
    id: str
    client_id: str
    quiz_top_size: int
    quiz_bottom_size: int
    quiz_shoe_size: int
    price_tier: str
    style_tags: List[str]
    learned_top_size: int
    learned_bottom_size: int
    learned_shoe_size: int
    fit_confidence: int
    feedback_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    size: int
    price_cents: int
    style_tags: List[str]
    status: str
    total_stock: int
    available_count: int
    reserved_count: int
    sold_count: int
    created_at: str
    updated_at: str
    version: int


class Stylist(TypedDict):
    id: str
    email: str
    name: str
    max_concurrent_fixes: int
    status: str
    active_fix_count: int
    created_at: str
    updated_at: str
    version: int


class Fix(TypedDict):
    id: str
    client_id: str
    stylist_id: Optional[str]
    status: str
    scheduled_ship_date: str
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    checkout_deadline: Optional[str]
    item_count: int
    kept_count: int
    returned_count: int
    subtotal_cents: int
    estimated_charge_cents: Optional[int]
    charge_cents: Optional[int]
    buy_the_look_applied: bool
    shipping_fee_cents: int
    tax_cents: int
    styling_fee_charged_cents: int
    styling_fee_credit_cents: int
    styling_fee_forfeited_cents: int
    created_at: str
    updated_at: str
    version: int


class FixItem(TypedDict):
    id: str
    fix_id: str
    product_id: str
    price_cents: int
    size: int
    category: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnShipment(TypedDict):
    id: str
    fix_id: str
    status: str
    item_ids: List[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict):
    id: str
    client_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ------------------------------------------ Append-only records (id + created_at)
class FeedbackEntry(TypedDict):
    id: str
    client_id: str
    fix_item_id: str
    product_size: int
    category: str
    rating: str
    created_at: str


class Hold(TypedDict):
    id: str
    client_id: str
    start_date: str
    end_date: str
    created_at: str
