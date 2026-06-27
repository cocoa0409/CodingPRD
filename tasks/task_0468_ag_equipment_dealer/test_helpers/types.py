"""Domain types: entity TypedDicts, status enums, and the role enum.

All field names mirror the Ag Equipment Dealer PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────────────────────

class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    LEASED = "LEASED"
    AUCTION_LISTED = "AUCTION_LISTED"
    AUCTION_SOLD = "AUCTION_SOLD"
    REPOSSESSED = "REPOSSESSED"
    RETIRED = "RETIRED"


class FloorPlanNoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CURTAILMENT_DUE = "CURTAILMENT_DUE"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"


class TradeInStatus(str, Enum):
    APPRAISED = "APPRAISED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class DealStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    DELIVERED = "DELIVERED"
    UNWOUND = "UNWOUND"


class AuctionLotStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    CLOSED_MET = "CLOSED_MET"
    CLOSED_NO_SALE = "CLOSED_NO_SALE"
    SETTLED = "SETTLED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    CLOSED = "CLOSED"
    VOID = "VOID"


class WarrantyClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"
    PAID = "PAID"


class WholeGoodsOrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    PARTIAL_FULFILLED = "PARTIAL_FULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# ─── Domain value enums ──────────────────────────────────────────────────────

class Condition(str, Enum):
    NEW = "NEW"
    USED = "USED"


class CustomerType(str, Enum):
    RETAIL = "RETAIL"
    COMMERCIAL_AG = "COMMERCIAL_AG"
    GOVERNMENT = "GOVERNMENT"


class CreditTier(str, Enum):
    PRIME = "PRIME"
    STANDARD = "STANDARD"
    SUBPRIME = "SUBPRIME"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class DealType(str, Enum):
    SALE = "SALE"
    LEASE = "LEASE"
    AUCTION_SALE = "AUCTION_SALE"


class PartCategory(str, Enum):
    MECHANICAL = "MECHANICAL"
    FILTER = "FILTER"
    PRECISION_AG = "PRECISION_AG"
    TELEMATICS = "TELEMATICS"


class ClaimType(str, Enum):
    WARRANTY = "WARRANTY"
    PIP = "PIP"
    RECALL = "RECALL"


class SeasonProgram(str, Enum):
    EARLY_ORDER = "EARLY_ORDER"
    IN_SEASON = "IN_SEASON"
    LATE = "LATE"


class UserRole(str, Enum):
    DealerAdmin = "DealerAdmin"
    SalesRep = "SalesRep"
    FinanceManager = "FinanceManager"
    ServiceAdvisor = "ServiceAdvisor"
    PartsClerk = "PartsClerk"
    AuctionClerk = "AuctionClerk"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ──

class Unit(TypedDict):
    id: str
    stock_number: str
    condition: str
    model_code: str
    serial_number: str
    dealer_cost_cents: int
    list_price_cents: int
    engine_hours: int
    acquired_from_tradein_id: Optional[str]
    floor_planned: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FloorPlanNote(TypedDict):
    id: str
    unit_id: str
    principal_cents: int
    annual_rate_bps: int
    curtailment_paid_cents: int
    interest_accrued_cents: int
    days_outstanding: int
    activated_on: Optional[str]
    curtailment_stage: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    customer_type: str
    credit_tier: str
    tax_exempt: bool
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    model_code: str
    serial_number: str
    engine_hours: int
    appraised_value_cents: int
    condition_grade: str
    base_value_cents: int
    minted_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    unit_id: str
    customer_id: str
    deal_type: str
    sale_price_cents: int
    lease_term_months: int
    tradein_id: Optional[str]
    trade_allowance_cents: int
    tax_cents: int
    monthly_payment_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionLot(TypedDict):
    id: str
    unit_id: str
    reserve_price_cents: int
    opens_at: str
    closes_at: str
    high_bid_cents: int
    high_bidder_customer_id: Optional[str]
    winning_deal_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    unit_id: str
    customer_id: str
    complaint: str
    labor_rate_cents: int
    flat_rate_hours: float
    actual_hours: float
    warranty_claim_id: Optional[str]
    labor_charge_cents: int
    parts_charge_cents: int
    total_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartLine(TypedDict):
    id: str
    work_order_id: str
    part_id: str
    quantity: int
    unit_price_cents: int
    extended_cents: int
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    sku: str
    description: str
    category: str
    unit_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    unit_id: str
    claim_type: str
    campaign_code: Optional[str]
    claimed_cents: int
    approved_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WholeGoodsOrder(TypedDict):
    id: str
    customer_id: str
    model_code: str
    season_program: str
    quantity: int
    unit_msrp_cents: int
    deposit_cents: int
    net_price_cents: int
    fulfilled_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false → only id + created_at) ─────────

class Bid(TypedDict):
    id: str
    lot_id: str
    bidder_customer_id: str
    amount_cents: int
    created_at: str
