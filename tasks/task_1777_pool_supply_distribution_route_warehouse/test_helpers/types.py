"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BRANCH_MANAGER = "BranchManager"
    COUNTER_REP = "CounterRep"
    ROUTE_DISPATCHER = "RouteDispatcher"
    WAREHOUSE_LEAD = "WarehouseLead"
    ACCOUNT = "Account"


class BranchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_SEASON = "CLOSED_SEASON"


class BranchPosture(str, Enum):
    NORMAL = "NORMAL"
    CONSTRAINED = "CONSTRAINED"
    FROZEN = "FROZEN"


class AccountType(str, Enum):
    DEALER = "DEALER"
    SERVICE_CO = "SERVICE_CO"


class AccountTier(str, Enum):
    PRO = "PRO"
    ELITE = "ELITE"
    PREMIER = "PREMIER"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductFamily(str, Enum):
    CHEMICAL = "CHEMICAL"
    EQUIPMENT = "EQUIPMENT"
    PARTS = "PARTS"


class HazmatClass(str, Enum):
    NONE = "NONE"
    OXIDIZER_5_1 = "OXIDIZER_5_1"
    CORROSIVE_8 = "CORROSIVE_8"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CommitmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"
    SUPERSEDED = "SUPERSEDED"


class OrderChannel(str, Enum):
    WILL_CALL = "WILL_CALL"
    ROUTE_DELIVERY = "ROUTE_DELIVERY"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PICKED_LOADED = "PICKED_LOADED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class BackorderStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO = "MORE_INFO"
    APPROVED = "APPROVED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class RmaReason(str, Enum):
    DEFECTIVE = "DEFECTIVE"
    WRONG_ITEM = "WRONG_ITEM"
    OVERSTOCK = "OVERSTOCK"
    EXPIRED = "EXPIRED"


class RmaStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"
    DENIED = "DENIED"


# --- Entity TypedDicts (common_fields: id, created_at, updated_at, version) ---


class Branch(TypedDict):
    id: str
    branch_code: str
    hazmat_storage_certified: bool
    peak_season_start: str
    peak_season_end: str
    willcall_cutoff_minutes: int
    seasonal_pool_units: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    account_number: str
    account_type: str
    tier: str
    ytd_volume_cents: int
    hazmat_delivery_license_expiry: Optional[str]
    willcall_authorized: bool
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    product_family: str
    hazmat_class: str
    base_price_cents: int
    expiry_tracked: bool
    low_stock_floor: int
    shortage_freeze_threshold: int
    created_at: str
    updated_at: str
    version: int


class StockLot(TypedDict):
    id: str
    branch_id: str
    product_id: str
    lot_code: str
    qty_on_hand: int
    qty_reserved_willcall: int
    qty_reserved_route: int
    qty_available: int
    expiry_date: Optional[str]
    hazmat_storage_class: str
    created_at: str
    updated_at: str
    version: int


class SeasonalProgram(TypedDict):
    id: str
    branch_id: str
    program_name: str
    order_window_start: str
    order_window_end: str
    ship_window_start: str
    ship_window_end: str
    early_buy_discount_pct: float
    pool_cap_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalCommitment(TypedDict):
    id: str
    program_id: str
    account_id: str
    committed_units: int
    consumed_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    branch_id: str
    account_id: str
    channel: str
    commitment_id: Optional[str]
    fulfillment_status: str
    payment_status: str
    order_subtotal_cents: int
    freight_charge_cents: int
    invoiced_cents: int
    tier_at_confirm: Optional[str]
    route_date: Optional[str]
    requested_pickup_slot: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    # Lightweight child record: carries ONLY id + created_at as common fields;
    # updated_at and version are absent (PRD §2.4).
    id: str
    order_id: str
    product_id: str
    qty: int
    unit_price_cents: int
    extended_price_cents: int
    allocated_lot_id: Optional[str]
    allocated_qty: int
    backordered_qty: int
    created_at: str


class BackorderRequest(TypedDict):
    id: str
    branch_id: str
    order_line_id: str
    product_id: str
    account_id: str
    qty_open: int
    qty_original: int
    priority_rank: int
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCenter(TypedDict):
    id: str
    center_name: str
    region_code: str
    authorized_brands: List[str]
    labor_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    account_id: str
    product_id: str
    serial_number: str
    brand: str
    purchase_date: str
    failure_description: str
    assigned_center_id: str
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    actual_labor_hours: Optional[float]
    info_cycles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict):
    id: str
    account_id: str
    order_id: str
    product_id: str
    lot_id: str
    qty: int
    reason: str
    restocking_fee_pct: float
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
