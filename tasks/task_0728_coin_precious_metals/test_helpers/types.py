"""Domain types: entity TypedDicts, status enums, role enum.

All money is integer cents; metal weights are troy ounces (real numbers).
Every persisted resource carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Enums ────────────────────────────────────────────────────────────

class Metal(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    PLATINUM = "PLATINUM"
    PALLADIUM = "PALLADIUM"


class ProductType(str, Enum):
    BULLION = "BULLION"
    NUMISMATIC = "NUMISMATIC"


class InventoryLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class IRAAccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SellOrderStatus(str, Enum):
    PLACED = "PLACED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class BuyOrderStatus(str, Enum):
    PLACED = "PLACED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class LayawayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class ConsignmentStatus(str, Enum):
    INTAKE = "INTAKE"
    LISTED = "LISTED"
    SOLD = "SOLD"
    RETURNED = "RETURNED"


class HedgePositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AppraisalAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class AuctionSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"


class UserRole(str, Enum):
    TRADER = "Trader"
    SALES_AGENT = "SalesAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER = "Customer"


# ─── Entity TypedDicts (all common_fields: true) ──────────────────────

class SpotRate(TypedDict):
    id: str
    metal: str
    price_per_troy_oz_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    product_type: str
    metal: str
    weight_troy_oz: float
    purity: float
    min_sell_spread_pct: float
    buy_spread_pct: float
    numismatic_premium_cents: int
    ira_eligible: bool
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    total_qty: int
    available_qty: int
    reserved_qty: int
    sold_qty: int
    acquisition_unit_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    id_document_on_file: bool
    lifetime_buy_payout_cents: int
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class IRAAccount(TypedDict):
    id: str
    customer_id: str
    custodian_name: str
    custodian_account_ref: str
    status: str
    allocated_value_cents: int
    created_at: str
    updated_at: str
    version: int


class SellOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity: int
    ira_account_id: Optional[str]
    quoted_unit_price_cents: int
    provisional_cogs_cents: int
    final_cogs_cents: Optional[int]
    total_price_cents: int
    realized_margin_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity: int
    quoted_unit_payout_cents: int
    total_payout_cents: int
    reportable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Layaway(TypedDict):
    id: str
    customer_id: str
    product_id: str
    inventory_lot_id: str
    quantity: int
    locked_unit_price_cents: int
    total_price_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    customer_id: str
    description: str
    reserve_price_cents: int
    commission_pct: float
    buyer_premium_pct: float
    auction_session_id: Optional[str]
    hammer_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class HedgePosition(TypedDict):
    id: str
    metal: str
    short_troy_oz: float
    entry_spot_cents: int
    exit_spot_cents: Optional[int]
    unrealized_pnl_cents: int
    realized_pnl_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    consignment_id: str
    hammer_price_cents: int
    commission_cents: int
    buyer_premium_cents: int
    seller_proceeds_cents: int
    dealer_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict):
    id: str
    name: str
    specialty_metal: str
    created_at: str
    updated_at: str
    version: int


class AppraisalAppointment(TypedDict):
    id: str
    appraiser_id: str
    consignment_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionSession(TypedDict):
    id: str
    room: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
