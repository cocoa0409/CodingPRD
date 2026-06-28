"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain are mutable and carry id, created_at, updated_at,
and version (see PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---

class UserRole(str, Enum):
    INVENTORY_MANAGER = "InventoryManager"
    PURCHASING_AGENT = "PurchasingAgent"
    BAR_MANAGER = "BarManager"


# --- Status enums ---

class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ParSettingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class MenuItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"


class MenuClass(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    STAR = "STAR"
    PLOWHORSE = "PLOWHORSE"
    PUZZLE = "PUZZLE"
    DOG = "DOG"


class CountSessionStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class CountMethod(str, Enum):
    UNITS = "UNITS"
    WEIGHT = "WEIGHT"


class ContainerType(str, Enum):
    BOTTLE = "BOTTLE"
    KEG = "KEG"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOID = "VOID"


class WasteReason(str, Enum):
    SPILL = "SPILL"
    BREAKAGE = "BREAKAGE"
    EXPIRY = "EXPIRY"
    OVERPOUR = "OVERPOUR"
    COMP = "COMP"


# --- Entity TypedDicts (all common_fields: true) ---

class Product(TypedDict):
    id: str
    sku: str
    name: str
    container_type: str
    container_volume_ml: float
    empty_container_weight_g: float
    density_g_per_ml: float
    unit_cost_cents: int
    case_pack: int
    on_hand_units: float
    status: str
    needs_reorder: bool
    created_at: str
    updated_at: str
    version: int


class ParSetting(TypedDict):
    id: str
    product_id: str
    par_level_units: float
    reorder_point_units: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RecipeSpec(TypedDict):
    id: str
    name: str
    recipe_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecipeLine(TypedDict):
    id: str
    recipe_id: str
    product_id: str
    pour_ml: float
    line_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    recipe_id: str
    menu_price_cents: int
    units_sold: int
    pour_cost_pct: float
    menu_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CountSession(TypedDict):
    id: str
    label: str
    counted_at: str
    status: str
    total_variance_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class CountLine(TypedDict):
    id: str
    count_session_id: str
    product_id: str
    count_method: str
    counted_units: float
    gross_weight_g: float
    closing_units: float
    theoretical_units: float
    variance_units: float
    variance_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    vendor_name: str
    expected_at: str
    status: str
    ordered_total_cents: int
    created_at: str
    updated_at: str
    version: int


class POLine(TypedDict):
    id: str
    purchase_order_id: str
    product_id: str
    ordered_qty: int
    unit_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    purchase_order_id: str
    vendor_invoice_no: str
    freight_cents: int
    status: str
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    invoice_total_cents: int
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    product_id: str
    received_qty: int
    unit_cost_cents: int
    extension_cents: int
    created_at: str
    updated_at: str
    version: int


class WasteLog(TypedDict):
    id: str
    product_id: str
    reason: str
    wasted_units: float
    waste_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class KegTap(TypedDict):
    id: str
    product_id: str
    draft_line_no: int
    tapped_from: str
    tapped_until: str
    created_at: str
    updated_at: str
    version: int
