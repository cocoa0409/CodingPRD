"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.8, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class SourcingChannel(str, Enum):
    FRANCHISED = "FRANCHISED"
    OPEN_MARKET = "OPEN_MARKET"


class AllocationPolicy(str, Enum):
    BACKLOG_BASIS = "BACKLOG_BASIS"
    USAGE_BASIS = "USAGE_BASIS"


class CustomerStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    CREDIT_HOLD = "CREDIT_HOLD"


class RegistrationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ON_HOLD = "ON_HOLD"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_INSPECTION = "IN_INSPECTION"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class LotAuthenticity(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_INSPECTION = "PENDING_INSPECTION"
    AUTHENTICATED = "AUTHENTICATED"
    REJECTED = "REJECTED"


class AlternateApprovalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class AllocationRunStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPPLIER_APPROVED = "SUPPLIER_APPROVED"
    SUPPLIER_REJECTED = "SUPPLIER_REJECTED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class BuyBackStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"


class BuyBackKind(str, Enum):
    EXCESS_RETURN = "EXCESS_RETURN"
    SHORTAGE_BUYBACK = "SHORTAGE_BUYBACK"


class UserRole(str, Enum):
    DISTRIBUTOR_ADMIN = "DistributorAdmin"
    SALES_REP = "SalesRep"
    CUSTOMER_BUYER = "CustomerBuyer"
    WAREHOUSE_OPS = "WarehouseOps"
    QUALITY_INSPECTOR = "QualityInspector"
    SUPPLIER_ADMIN = "SupplierAdmin"


# All resources carry the common fields of PRD §2.8:
# id, created_at, updated_at, version.


class ManufacturerLine(TypedDict, total=False):
    id: str
    line_code: str
    name: str
    sourcing_channel: str
    ncnr: bool
    cancel_window_days: int
    reschedule_window_days: int
    allocation_policy: str
    open_debit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    id: str
    manufacturer_line_id: str
    part_number: str
    msl_level: int
    floor_life_hours: int
    date_code_limit_months: int
    standard_cost_cents: int
    book_price_cents: int
    qty_on_hand: int
    qty_reserved: int
    open_demand_qty: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    open_balance_cents: int
    trailing_12mo_purchases_cents: int
    trailing_12mo_component_usage_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DesignRegistration(TypedDict, total=False):
    id: str
    customer_id: str
    part_id: str
    end_customer_name: str
    registered_cost_cents: int
    max_registered_qty: int
    registered_qty_remaining: int
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict, total=False):
    id: str
    customer_id: str
    note: str
    status: str
    open_exposure_cents: int
    allocated_value_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    part_id: str
    quantity: int
    ship_date: str
    unit_price_cents: int
    ncnr_snapshot: bool
    cancel_window_days_snapshot: int
    reschedule_window_days_snapshot: int
    cancel_by_date: str
    allocated_qty: int
    shipped_qty: int
    returned_qty: int
    last_shipped_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    part_id: str
    date_code: str
    qty_received: int
    qty_on_hand: int
    qty_reserved: int
    qty_shipped: int
    source_type: str
    authenticity: str
    msl_exposure_hours: int
    last_baked_at: Optional[str]
    received_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MoistureExposure(TypedDict, total=False):
    id: str
    lot_id: str
    opened_at: str
    sealed_at: Optional[str]
    note: str
    created_at: str
    updated_at: str
    version: int


class AlternatePartApproval(TypedDict, total=False):
    id: str
    customer_id: str
    primary_part_id: str
    alternate_part_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationRunLine(TypedDict, total=False):
    order_line_id: str
    allocated_qty: int


class AllocationRun(TypedDict, total=False):
    id: str
    part_id: str
    basis: str
    total_supply_qty: int
    total_demand_qty: int
    lines: List[AllocationRunLine]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShipAndDebitClaim(TypedDict, total=False):
    id: str
    registration_id: str
    order_line_id: str
    qty: int
    standard_cost_cents: int
    registered_cost_cents: int
    amount_provisional_cents: int
    audited_cost_cents: Optional[int]
    amount_final_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyBackRequest(TypedDict, total=False):
    id: str
    customer_id: str
    order_line_id: str
    kind: str
    qty: int
    price_basis_cents: int
    fee_pct: float
    provisional_credit_cents: int
    received_qty: Optional[int]
    final_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
