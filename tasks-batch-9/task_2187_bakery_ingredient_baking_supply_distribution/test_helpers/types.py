"""Domain types: status enums, role enum and entity TypedDicts.

PRD §2.4: every persisted resource carries `id` and `created_at`, and almost
every one additionally carries `updated_at` and `version`. The single exception
is `CommodityIndexQuote`, which carries only `id` and `created_at` — its
TypedDict below deliberately omits `updated_at` and `version`.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER_BUYER = "CustomerBuyer"
    ACCOUNT_MANAGER = "AccountManager"
    PRICING_CONTROLLER = "PricingController"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    QUALITY_MANAGER = "QualityManager"
    TECHNICAL_SPECIALIST = "TechnicalSpecialist"
    LOGISTICS_PLANNER = "LogisticsPlanner"
    PLATFORM_ADMIN = "PlatformAdmin"


class AllergenClass(str, Enum):
    NONE = "NONE"
    GLUTEN = "GLUTEN"
    TREE_NUT = "TREE_NUT"
    PEANUT = "PEANUT"
    DAIRY = "DAIRY"
    EGG = "EGG"
    SOY = "SOY"


class AllergenProgram(str, Enum):
    STANDARD = "STANDARD"
    GLUTEN_FREE_CERTIFIED = "GLUTEN_FREE_CERTIFIED"
    NUT_FREE_CERTIFIED = "NUT_FREE_CERTIFIED"


class ProductCategory(str, Enum):
    FLOUR = "FLOUR"
    LEAVENING = "LEAVENING"
    FAT = "FAT"
    INCLUSION = "INCLUSION"
    PACKAGING = "PACKAGING"


class IndexCode(str, Enum):
    NONE = "NONE"
    HRW_WHEAT = "HRW_WHEAT"
    SRW_WHEAT = "SRW_WHEAT"
    SOFT_OIL = "SOFT_OIL"
    CANE_SUGAR = "CANE_SUGAR"


class PricingMode(str, Enum):
    ORDER_DATE_INDEX = "ORDER_DATE_INDEX"
    DELIVERY_DATE_INDEX = "DELIVERY_DATE_INDEX"


class DeliveryMode(str, Enum):
    BULK = "BULK"
    BAGGED = "BAGGED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class RiskTier(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class WarehouseZoneStatus(str, Enum):
    OPEN = "OPEN"
    SANITATION_LOCKOUT = "SANITATION_LOCKOUT"


class ForwardPricingContractStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DISPOSED = "DISPOSED"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"


class OrderFulfillmentStatus(str, Enum):
    NEW = "NEW"
    ALLOCATED = "ALLOCATED"
    ROUTED = "ROUTED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    SHORT_SHIPPED = "SHORT_SHIPPED"
    CANCELLED = "CANCELLED"


class OrderPricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    INVOICED = "INVOICED"
    VOID = "VOID"


class OrderLineAllocationStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    SHIPPED = "SHIPPED"


class SubstitutionRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DeliveryRouteStatus(str, Enum):
    PLANNING = "PLANNING"
    SEALED = "SEALED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    DELIVERED = "DELIVERED"
    SHORTED = "SHORTED"
    CANCELLED = "CANCELLED"


class TechSupportEngagementStatus(str, Enum):
    OPEN = "OPEN"
    BILLABLE = "BILLABLE"
    ATTACHED = "ATTACHED"
    WAIVED = "WAIVED"


class Customer(TypedDict):
    id: str
    legal_name: str
    allergen_program: str
    credit_limit_cents: int
    min_drop_cents: int
    status: str
    open_exposure_cents: int
    allergen_risk_score: float
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    category: str
    allergen_class: str
    bulk_capable: bool
    shelf_life_days: int
    index_code: str
    list_price_cents_per_lb: int
    min_rotation_days: int
    created_at: str
    updated_at: str
    version: int


class CommodityIndexQuote(TypedDict):
    """PRD §2.4: an immutable market observation carrying only `id` and
    `created_at` — it has neither `updated_at` nor `version`."""

    id: str
    index_code: str
    effective_on: str
    price_cents_per_lb: int
    created_at: str


class ForwardPricingContract(TypedDict):
    id: str
    customer_id: str
    term_start_on: str
    term_end_on: str
    pricing_mode: str
    status: str
    negotiation_round: int
    committed_volume_lb: float
    drawn_volume_lb: float
    authored_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractLine(TypedDict):
    id: str
    contract_id: str
    product_id: str
    volume_committed_lb: float
    basis_cents_per_lb: int
    cap_cents_per_lb: Optional[int]
    volume_drawn_lb: float
    created_at: str
    updated_at: str
    version: int


class WarehouseZone(TypedDict):
    id: str
    zone_code: str
    allergen_class: str
    status: str
    on_hand_lb: float
    lockout_start_at: Optional[str]
    lockout_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    lot_code: str
    product_id: str
    zone_id: str
    manufactured_on: str
    expires_on: str
    quantity_received_lb: float
    quantity_on_hand_lb: float
    quantity_reserved_lb: float
    quantity_consumed_lb: float
    status: str
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiloAsset(TypedDict):
    id: str
    silo_code: str
    customer_id: str
    product_id: str
    capacity_lb: float
    min_fill_lb: float
    residual_lb: float
    last_fill_window_start_at: Optional[str]
    last_fill_window_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    contract_id: Optional[str]
    delivery_mode: str
    requested_delivery_on: str
    order_placed_on: Optional[str]
    delivered_on: Optional[str]
    fulfillment_status: str
    pricing_status: str
    surge_window: bool
    subtotal_cents: int
    fuel_surcharge_cents: int
    tech_attach_fee_cents: int
    volume_rebate_cents: int
    total_cents: int
    short_ship_lb: float
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity_lb: float
    unit_price_cents: int
    extended_cents: int
    allocation_status: str
    lot_id: Optional[str]
    silo_id: Optional[str]
    contract_line_id: Optional[str]
    substituted_from_product_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict):
    id: str
    order_line_id: str
    proposed_product_id: str
    rationale: str
    status: str
    revision_round: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    route_code: str
    service_on: str
    vehicle_capacity_lb: float
    service_buffer_minutes: int
    status: str
    allergen_class_lock: str
    planned_load_lb: float
    utilization_pct: float
    stop_count: int
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    order_id: str
    window_start_at: str
    window_end_at: str
    sequence_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TechSupportEngagement(TypedDict):
    id: str
    customer_id: str
    product_id: str
    order_id: Optional[str]
    status: str
    hours_logged: float
    attach_fee_cents: int
    assigned_specialist_user_id: str
    created_at: str
    updated_at: str
    version: int
