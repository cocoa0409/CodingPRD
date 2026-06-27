"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the Grain Elevator Coop PRD §1-§4.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    MERCHANDISER = "Merchandiser"
    GRADE_CLERK = "GradeClerk"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    SHIPPING_CLERK = "ShippingClerk"
    RISK_MANAGER = "RiskManager"


# --- Status enums (PRD §3) ---
class ScaleTicketStatus(str, Enum):
    WEIGHED = "WEIGHED"
    GRADED = "GRADED"
    SETTLED_IN = "SETTLED_IN"
    VOIDED = "VOIDED"


class StoragePositionStatus(str, Enum):
    STORED = "STORED"
    CHARGE_FROZEN = "CHARGE_FROZEN"
    DEPLETED = "DEPLETED"
    VOIDED = "VOIDED"


class WarehouseReceiptStatus(str, Enum):
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"


class ContractType(str, Enum):
    CASH = "CASH"
    FORWARD = "FORWARD"
    BASIS = "BASIS"
    HTA = "HTA"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    PRICED = "PRICED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class StorageBasis(str, Enum):
    ESTIMATE = "ESTIMATE"
    ACTUAL = "ACTUAL"


class DepositAccountType(str, Enum):
    DELAYED_PRICE = "DELAYED_PRICE"
    WAREHOUSE_RECEIPT = "WAREHOUSE_RECEIPT"


class ShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOADED = "LOADED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class DryingReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class HedgePositionSide(str, Enum):
    SHORT = "SHORT"
    LONG = "LONG"


class HedgePositionStatus(str, Enum):
    OPEN = "OPEN"
    MARGIN_CALL = "MARGIN_CALL"
    CLOSED = "CLOSED"


class PatronagePeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CommoditySymbol(str, Enum):
    CORN = "CORN"
    SOYBEANS = "SOYBEANS"
    WHEAT = "WHEAT"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---


class Commodity(TypedDict):
    id: str
    symbol: str
    test_weight_lbs_per_bushel: float
    base_moisture_pct: float
    shrink_pct_per_point: float
    drying_cents_per_point_per_bushel: float
    futures_contract_bushels: int
    created_at: str
    updated_at: str
    version: int


class PriceBoard(TypedDict):
    id: str
    commodity_id: str
    futures_price: float
    cash_basis: float
    cash_price: float
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    name: str
    equity_credit_dollars: float
    cash_paid_dollars: float
    net_priced_bushels: float
    created_at: str
    updated_at: str
    version: int


class ScaleTicket(TypedDict):
    id: str
    member_id: str
    commodity_id: str
    gross_weight_lbs: float
    tare_weight_lbs: float
    moisture_pct: float
    dockage_pct: float
    status: str
    net_weight_lbs: float
    clean_weight_lbs: float
    moisture_points: float
    wet_bushels: float
    net_dry_bushels: float
    drying_charge_dollars: float
    deposit_account_type: str
    storage_position_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StoragePosition(TypedDict):
    id: str
    member_id: str
    commodity_id: str
    scale_ticket_id: str
    program: str
    bushels: float
    bushels_available: float
    status: str
    storage_start_date: str
    frozen_days: int
    receipt_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarehouseReceipt(TypedDict):
    id: str
    storage_position_id: str
    member_id: str
    bushels: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    member_id: str
    commodity_id: str
    contract_type: str
    contracted_bushels: float
    futures_leg: Optional[float]
    basis_leg: Optional[float]
    net_price: Optional[float]
    status: str
    priced_bushels: float
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    contract_id: str
    storage_position_id: str
    priced_bushels: float
    storage_basis: str
    gross_proceeds_dollars: float
    storage_charge_dollars: float
    net_proceeds_dollars: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadoutBay(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class DryerLine(TypedDict):
    id: str
    name: str
    cleanout_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class DryingReservation(TypedDict):
    id: str
    dryer_line_id: str
    scale_ticket_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    commodity_id: str
    storage_position_id: str
    loadout_bay_id: str
    bushels: float
    bay_window_start: str
    bay_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HedgePosition(TypedDict):
    id: str
    commodity_id: str
    side: str
    contracts: int
    entry_futures_price: float
    mark_futures_price: Optional[float]
    posted_margin_dollars: float
    unrealized_pnl_dollars: float
    account_equity_dollars: float
    margin_call_dollars: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PatronagePeriod(TypedDict):
    id: str
    label: str
    pool_dollars: float
    qualified_cash_pct: float
    status: str
    total_bushels: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class PatronageAllocation(TypedDict):
    id: str
    patronage_period_id: str
    member_id: str
    member_bushels: float
    allocation_dollars: float
    cash_dollars: float
    equity_dollars: float
    created_at: str
