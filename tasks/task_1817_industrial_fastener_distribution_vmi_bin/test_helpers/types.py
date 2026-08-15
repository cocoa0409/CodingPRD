"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_CAPACITY = "AT_CAPACITY"
    RETIRED = "RETIRED"


class ComplianceFlag(str, Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class PricingMode(str, Enum):
    UNIT_PRICE = "UNIT_PRICE"
    COST_PER_BIN = "COST_PER_BIN"


class DeliveryMode(str, Enum):
    DOCK_TO_STOCK = "DOCK_TO_STOCK"
    LINE_SIDE = "LINE_SIDE"


class RouteStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ON_HOLD = "ON_HOLD"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class CertStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class KitJobStatus(str, Enum):
    DRAFT = "DRAFT"
    PICKING = "PICKING"
    ON_HOLD = "ON_HOLD"
    PACKED = "PACKED"
    COMPLETED = "COMPLETED"
    SCRAPPED = "SCRAPPED"


class UserRole(str, Enum):
    DISTRIBUTOR_ADMIN = "DistributorAdmin"
    ROUTE_DRIVER = "RouteDriver"
    WAREHOUSE_OPERATOR = "WarehouseOperator"


# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
class CustomerSite(TypedDict, total=False):
    id: str
    name: str
    ship_to_code: str
    status: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    delivery_mode: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    sku: str
    description: str
    status: str
    is_critical: bool
    unit_price_cents: int
    total_stock_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


# Append-only declaration (PRD §2.5): carries ONLY id + created_at,
# never updated_at or version.
class PartCrossReference(TypedDict, total=False):
    id: str
    created_at: str
    from_part_id: str
    to_part_id: str
    priority_rank: int
    is_active: bool


class BinAgreement(TypedDict, total=False):
    id: str
    site_id: str
    part_id: str
    bin_location: str
    pricing_mode: str
    flat_bin_price_cents: int
    min_qty: int
    max_qty: int
    on_hand_qty: int
    open_order_qty: int
    status: str
    compliance_flag: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentRoute(TypedDict, total=False):
    id: str
    site_id: str
    route_date: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    bin_agreement_id: str
    counted_qty: Optional[int]
    status: str
    generated_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict, total=False):
    id: str
    bin_agreement_id: str
    site_id: str
    part_id: str
    ordered_qty: int
    unit_price_cents: int
    total_price_cents: int
    delivery_mode: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LotCertificate(TypedDict, total=False):
    id: str
    part_id: str
    lot_number: str
    cert_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class KitJob(TypedDict, total=False):
    id: str
    site_id: str
    kit_name: str
    component_part_ids: List[str]
    qty_per_part: int
    kit_count: int
    station_window_start: str
    station_window_end: str
    packaging_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
