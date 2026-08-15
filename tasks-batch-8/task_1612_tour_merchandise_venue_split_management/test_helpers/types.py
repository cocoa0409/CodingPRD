"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    TOUR_MANAGER = "TourManager"
    SELLER = "Seller"
    ACCOUNTANT = "Accountant"
    VENUE_REP = "VenueRep"


class TourStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ShowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CommissionMode(str, Enum):
    FLAT = "FLAT"
    TIERED = "TIERED"


class ProductType(str, Enum):
    REGULAR = "REGULAR"
    BUNDLE = "BUNDLE"


class RoyaltyTreatment(str, Enum):
    STANDARD = "STANDARD"
    LICENSED = "LICENSED"


class Size(str, Enum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    OS = "OS"


class SellerSessionStatus(str, Enum):
    OPEN = "OPEN"
    COUNTED_OUT = "COUNTED_OUT"
    VERIFIED = "VERIFIED"
    LOCKED = "LOCKED"


class Tender(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


class SaleRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class OnlineOrderStatus(str, Enum):
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class OriginType(str, Enum):
    WAREHOUSE = "WAREHOUSE"
    SHOW = "SHOW"


class VerifyDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class CloseoutAction(str, Enum):
    RETURN = "RETURN"
    LIQUIDATE = "LIQUIDATE"


class Tour(TypedDict, total=False):
    id: str
    name: str
    artist_name: str
    default_size_curve: Dict[str, int]
    cash_variance_tolerance_cents: int
    standard_rate_bps: int
    tier_threshold_cents: int
    tier_bonus_bps: int
    licensed_flat_per_unit_cents: int
    licensed_rate_bps: int
    status: str
    royalty_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict, total=False):
    id: str
    tour_id: str
    city: str
    venue_name: str
    show_date: str
    commission_mode: str
    flat_commission_bps: Optional[int]
    commission_tiers: Optional[List[Dict[str, Any]]]
    size_curve: Optional[Dict[str, int]]
    status: str
    settlement_id: Optional[str]
    closeout_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    tour_id: str
    sku: str
    name: str
    product_type: str
    royalty_treatment: str
    sized: bool
    base_price_cents: int
    bundle_components: Optional[List[Dict[str, Any]]]
    initial_stock_by_size: Dict[str, int]
    warehouse_stock_by_size: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class ShowProduct(TypedDict, total=False):
    id: str
    show_id: str
    product_id: str
    price_cents: int
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    show_id: str
    product_id: str
    size: str
    quantity_allocated: int
    quantity_sold: int
    quantity_returned: int
    quantity_liquidated: int
    quantity_shrunk: int
    quantity_on_hand: int
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict, total=False):
    id: str
    tour_id: str
    display_name: str
    seller_code: str
    created_at: str
    updated_at: str
    version: int


class SellerSession(TypedDict, total=False):
    id: str
    show_id: str
    seller_id: str
    cash_float_cents: int
    status: str
    counted_cash_cents: Optional[int]
    expected_cash_cents: int
    cash_variance_cents: Optional[int]
    verified_by_user_id: Optional[str]
    recount_count: int
    created_at: str
    updated_at: str
    version: int


class SaleRecord(TypedDict, total=False):
    id: str
    session_id: str
    allocation_id: str
    show_id: str
    product_id: str
    quantity: int
    tender: str
    unit_price_cents: int
    gross_cents: int
    status: str
    void_reason: Optional[str]
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OnlineOrder(TypedDict, total=False):
    id: str
    tour_id: str
    product_id: str
    size: Optional[str]
    quantity: int
    unit_price_cents: int
    gross_cents: int
    artist_royalty_provisional_cents: int
    licensing_provisional_cents: int
    artist_royalty_final_cents: Optional[int]
    licensing_final_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    show_id: str
    status: str
    provisional_gross_cents: int
    venue_commission_provisional_cents: int
    final_gross_cents: Optional[int]
    venue_commission_final_cents: Optional[int]
    net_to_tour_cents: Optional[int]
    artist_royalty_cents: Optional[int]
    licensing_cents: Optional[int]
    company_share_cents: Optional[int]
    pinned_standard_rate_bps: int
    pinned_tier_threshold_cents: int
    pinned_tier_bonus_bps: int
    pinned_licensed_flat_per_unit_cents: int
    pinned_licensed_rate_bps: int
    reconciled_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    tour_id: str
    origin_type: str
    origin_show_id: Optional[str]
    destination_show_id: str
    lines: List[Dict[str, Any]]
    status: str
    dispatched_by_user_id: Optional[str]
    dispatched_at: Optional[str]
    received_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
