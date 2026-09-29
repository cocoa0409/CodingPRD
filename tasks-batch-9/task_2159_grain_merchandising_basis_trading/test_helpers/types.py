"""Domain types for the Grain Merchandising & Basis Trading API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────

class UserRole(str, Enum):
    DESK_ADMIN = "DeskAdmin"
    MERCHANDISER = "Merchandiser"
    FUTURES_TRADER = "FuturesTrader"
    RISK_OFFICER = "RiskOfficer"
    GRAIN_INSPECTOR = "GrainInspector"
    FREIGHT_COORDINATOR = "FreightCoordinator"


# ─── Domain enums ─────────────────────────────────────

class CommodityCode(str, Enum):
    CORN = "CORN"
    SOYBEANS = "SOYBEANS"
    HRW_WHEAT = "HRW_WHEAT"


class DeskPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class DiscountScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RiskLimitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class HedgePositionSide(str, Enum):
    SHORT = "SHORT"
    LONG = "LONG"


class HedgePositionStatus(str, Enum):
    OPEN = "OPEN"
    MARGIN_CALL = "MARGIN_CALL"
    LIQUIDATED = "LIQUIDATED"


class MarginCallStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    DEFAULTED = "DEFAULTED"


class ContractType(str, Enum):
    CASH = "CASH"
    HTA = "HTA"
    BASIS = "BASIS"
    DEFERRED = "DEFERRED"


class SettlementBasis(str, Enum):
    SHRINK_FIRST = "SHRINK_FIRST"
    GROSS_GRADE = "GROSS_GRADE"


class PricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PARTIALLY_PRICED = "PARTIALLY_PRICED"
    FULLY_PRICED = "FULLY_PRICED"


class DeliveryStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    COMPLETE = "COMPLETE"


class PurchaseContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    DEFAULTED = "DEFAULTED"
    ROLLED = "ROLLED"


class DeliveryTicketStatus(str, Enum):
    GRADED = "GRADED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class FreightBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PricingComponent(str, Enum):
    FUTURES = "FUTURES"
    BASIS = "BASIS"


class DamagesMethod(str, Enum):
    MARKET_LOSS = "MARKET_LOSS"
    REPLACEMENT_COST = "REPLACEMENT_COST"


class DiscountFactor(str, Enum):
    MOISTURE = "MOISTURE"
    TEST_WEIGHT = "TEST_WEIGHT"
    FOREIGN_MATERIAL = "FOREIGN_MATERIAL"
    DAMAGE = "DAMAGE"


class TierDirection(str, Enum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"


class RiskLimitReportStatus(str, Enum):
    WITHIN = "WITHIN"
    BREACH = "BREACH"
    NO_LIMIT = "NO_LIMIT"


# ─── Entity shapes ────────────────────────────────────
# Every entity below carries id / created_at / updated_at / version
# (PRD §2.4), except PricingOrder, which is an immutable event row and
# carries only id and created_at.


class TradingDesk(TypedDict):
    id: str
    desk_code: str
    name: str
    credit_line_usd: float
    margin_requirement_usd: float
    open_margin_call_usd: float
    credit_utilization: float
    available_credit_usd: float
    posture: str
    committed_hedge_lots: int
    open_bushel_commitment: float
    unpriced_bushels: float
    realized_hedge_pnl_usd: float
    created_at: str
    updated_at: str
    version: int


class ElevatorLocation(TypedDict):
    id: str
    desk_id: str
    location_code: str
    name: str
    intake_capacity_bushels: int
    rail_served: bool
    committed_intake_bushels: float
    created_at: str
    updated_at: str
    version: int


class DiscountSchedule(TypedDict):
    id: str
    commodity_code: str
    effective_from: str
    moisture_standard_pct: float
    shrink_factor_pct_per_point: float
    tiers: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskLimit(TypedDict):
    id: str
    desk_id: str
    commodity_code: str
    max_unpriced_bushels: int
    max_net_short_lots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RailFleet(TypedDict):
    id: str
    home_location_id: str
    fleet_code: str
    car_count: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    location_id: str
    commodity_code: str
    futures_month: str
    delivery_period_start: str
    delivery_period_end: str
    basis_cents: float
    max_bushels: int
    expires_at: str
    contracted_bushels: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HedgePosition(TypedDict):
    id: str
    desk_id: str
    commodity_code: str
    futures_month: str
    side: str
    lots_open: int
    avg_entry_price_cents: float
    lots_committed: int
    lots_available: int
    posted_margin_usd: float
    last_settlement_price_cents: float
    unrealized_pnl_usd: float
    realized_pnl_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseContract(TypedDict):
    id: str
    bid_id: str
    desk_id: str
    location_id: str
    hedge_position_id: str
    rolled_from_contract_id: Optional[str]
    contract_type: str
    commodity_code: str
    futures_month: str
    seller_name: str
    bushels: float
    delivery_start: str
    delivery_end: str
    settlement_basis: str
    futures_price_cents: Optional[float]
    basis_cents: Optional[float]
    roll_adjustment_cents: float
    gross_unit_price_cents: Optional[float]
    priced_futures_bushels: float
    priced_basis_bushels: float
    unpriced_bushels: float
    hedge_lots_assigned: int
    delivered_bushels: float
    settled_value_usd: float
    damages_usd: float
    termination_reason: Optional[str]
    created_by_user_id: str
    pricing_locked: bool
    pricing_status: str
    delivery_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable event row (PRD §2.4, §3.5): id + created_at only.
class PricingOrder(TypedDict):
    id: str
    contract_id: str
    component: str
    bushels: float
    price_cents: float
    placed_by_user_id: str
    created_at: str


class MarginCall(TypedDict):
    id: str
    hedge_position_id: str
    call_amount_usd: float
    issued_at: str
    cure_deadline_at: str
    cured_amount_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTicket(TypedDict):
    id: str
    contract_id: str
    location_id: str
    freight_booking_id: Optional[str]
    discount_schedule_id: str
    gross_bushels: float
    moisture_pct: float
    test_weight_lbs: float
    foreign_material_pct: float
    damage_pct: float
    shrink_pct: float
    net_bushels: float
    discount_total_usd: float
    gross_contract_value_usd: Optional[float]
    service_fee_cents_per_bushel: Optional[float]
    net_unit_price_cents: Optional[float]
    settlement_value_usd: Optional[float]
    disposition_reason: Optional[str]
    graded_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FreightBooking(TypedDict):
    id: str
    fleet_id: str
    contract_id: str
    cars_requested: int
    placement_at: str
    release_at: str
    occupancy_end_at: str
    substitution_count: int
    cancellation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PositionReport(TypedDict):
    desk_id: str
    commodity_code: Optional[str]
    cash_long_bushels: float
    unpriced_bushels: float
    net_futures_lots: int
    required_hedge_lots: int
    hedge_coverage_ratio: float
    margin_requirement_usd: float
    open_margin_call_usd: float
    credit_utilization: float
    posture: str
    risk_limit_status: str
