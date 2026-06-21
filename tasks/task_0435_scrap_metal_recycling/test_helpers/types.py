"""Domain types: entity TypedDicts, status enums, role enum for the scrap-metal yard API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FLAGGED = "FLAGGED"
    BANNED = "BANNED"


class IdType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    STATE_ID = "STATE_ID"
    PASSPORT = "PASSPORT"


class Category(str, Enum):
    FERROUS = "FERROUS"
    NON_FERROUS = "NON_FERROUS"


class CommodityPriceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ScaleTicketStatus(str, Enum):
    DRAFT = "DRAFT"
    WEIGHED = "WEIGHED"
    HOLD = "HOLD"
    RELEASED = "RELEASED"
    REPORTED = "REPORTED"
    PAID = "PAID"


class PayoutMethod(str, Enum):
    CASH = "CASH"
    CHECK = "CHECK"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ContainerStatus(str, Enum):
    STAGED = "STAGED"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class MillShipmentStatus(str, Enum):
    SHIPPED = "SHIPPED"
    SETTLED = "SETTLED"


class HedgePositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TheftReportStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    WEIGH_MASTER = "WeighMaster"
    PAYOUT_CLERK = "PayoutClerk"
    YARD_MANAGER = "YardManager"
    SETTLEMENT_ACCOUNTANT = "SettlementAccountant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Entity TypedDicts — mutable entities carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Seller(TypedDict):
    id: str
    legal_name: str
    id_type: str
    id_number: str
    tin: Optional[str]
    status: str
    ytd_cash_paid_cents: int
    requires_1099: bool
    open_theft_reports: int
    created_at: str
    updated_at: str
    version: int


class CommodityPrice(TypedDict):
    id: str
    grade_code: str
    category: str
    spot_price_cents_per_lb: int
    mill_price_cents_per_lb: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScaleTicket(TypedDict):
    id: str
    seller_id: str
    container_id: Optional[str]
    gross_weight_lb: float
    tare_weight_lb: Optional[float]
    net_weight_lb: Optional[float]
    status: str
    gross_valuation_cents: int
    theft_hold_released_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    ticket_id: str
    seller_id: str
    method: str
    amount_cents: int
    form_1099_issued: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict):
    id: str
    category: str
    capacity_lb: float
    loaded_weight_lb: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MillShipment(TypedDict):
    id: str
    container_id: str
    category: str
    shipped_weight_lb: float
    expected_settlement_cents: int
    final_settlement_cents: Optional[int]
    settlement_variance_cents: Optional[int]
    hedge_position_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HedgePosition(TypedDict):
    id: str
    category: str
    hedged_weight_lb: float
    locked_price_cents_per_lb: int
    realized_weight_lb: float
    realized_pnl_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TheftReport(TypedDict):
    id: str
    seller_id: str
    ticket_id: Optional[str]
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entity — TicketLineItem carries ONLY id + created_at
# (no updated_at, no version)
# ---------------------------------------------------------------------------
class TicketLineItem(TypedDict):
    id: str
    ticket_id: str
    grade_code: str
    commodity_price_id: str
    weight_lb: float
    line_valuation_cents: int
    created_at: str
