"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProductCategory(str, Enum):
    SPICE = "SPICE"
    TEA = "TEA"
    HERB = "HERB"


class ProductKind(str, Enum):
    SIMPLE = "SIMPLE"
    BLEND = "BLEND"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class StockState(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    PRODUCED = "PRODUCED"


class AccountTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    CONFIRMED = "CONFIRMED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CATALOG_MANAGER = "CatalogManager"
    PRODUCTION_OPERATOR = "ProductionOperator"
    SALES_AGENT = "SalesAgent"
    WHOLESALER = "Wholesaler"


# --- Entity TypedDicts ---

# common_fields: true -> id + created_at + updated_at + version
class Product(TypedDict):
    id: str
    name: str
    category: str
    kind: str
    unit_price_cents_per_gram: float
    tare_default_grams: int
    allergen_tags: List[str]
    shelf_life_days: int
    status: str
    stock_state: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (immutable junction row)
class BlendComponent(TypedDict):
    id: str
    blend_product_id: str
    component_product_id: str
    weight_ratio_bps: int
    created_at: str


# common_fields: true
class InventoryLot(TypedDict):
    id: str
    product_id: str
    source_batch_id: Optional[str]
    lot_code: str
    grams_received: int
    grams_on_hand: int
    received_at: str
    best_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ProductionLine(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Batch(TypedDict):
    id: str
    blend_product_id: str
    production_line_id: str
    target_output_grams: int
    produced_grams: int
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LabelingStation(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class TinRun(TypedDict):
    id: str
    labeling_station_id: str
    product_ids: List[str]
    allergen_set: List[str]
    scheduled_start: str
    scheduled_end: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class WholesaleAccount(TypedDict):
    id: str
    business_name: str
    tier: str
    credit_limit_cents: int
    committed_exposure_cents: int
    projected_exposure_cents: int
    available_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class CustomerOrder(TypedDict):
    id: str
    wholesale_account_id: str
    fulfillment_status: str
    allergen_ack: bool
    total_net_grams: int
    provisional_total_cents: int
    final_total_cents: int
    held_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    requested_grams: int
    gross_grams: Optional[int]
    tare_grams: Optional[int]
    net_grams: Optional[int]
    allocated_lot_id: Optional[str]
    provisional_line_cents: int
    final_line_cents: int
    created_at: str
    updated_at: str
    version: int
