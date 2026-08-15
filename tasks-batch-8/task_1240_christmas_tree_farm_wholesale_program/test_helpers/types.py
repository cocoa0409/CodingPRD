"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SeasonPosture(str, Enum):
    PLANNING = "PLANNING"
    BOOKING = "BOOKING"
    HARVEST = "HARVEST"
    SHIPPING = "SHIPPING"
    SETTLEMENT = "SETTLEMENT"
    CLOSED = "CLOSED"


class BlockRotation(str, Enum):
    RESTING = "RESTING"
    PLANTED = "PLANTED"
    GROWING = "GROWING"
    HARVESTABLE = "HARVESTABLE"
    HARVESTED = "HARVESTED"


class Species(str, Enum):
    NOBLE_FIR = "NOBLE_FIR"
    DOUGLAS_FIR = "DOUGLAS_FIR"
    GRAND_FIR = "GRAND_FIR"
    NORDMANN_FIR = "NORDMANN_FIR"


class HeightClass(str, Enum):
    H_4_5 = "H_4_5"
    H_5_6 = "H_5_6"
    H_6_7 = "H_6_7"
    H_7_8 = "H_7_8"
    H_8_9 = "H_8_9"
    H_9_PLUS = "H_9_PLUS"


# Declared height-class ordering used by a lot's bucket listing.
HEIGHT_CLASS_ORDER: List[str] = [
    "H_4_5", "H_5_6", "H_6_7", "H_7_8", "H_8_9", "H_9_PLUS",
]


class CropLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"


class BuyerStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ALLOCATED = "ALLOCATED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CUT = "CUT"
    LOADED = "LOADED"
    RELEASED = "RELEASED"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAID_OFF = "LAID_OFF"


class TicketStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class PayBasis(str, Enum):
    PIECE = "PIECE"
    HOURLY_FLOOR = "HOURLY_FLOOR"


class LoadStatus(str, Enum):
    BUILDING = "BUILDING"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ConsignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class TagStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REDEEMED = "REDEEMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class CullReason(str, Enum):
    DISEASE = "DISEASE"
    DAMAGE = "DAMAGE"
    GRADING = "GRADING"
    OTHER = "OTHER"


class ReplantStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class UserRole(str, Enum):
    OWNER = "Owner"
    FARM_MANAGER = "FarmManager"
    WHOLESALE_BUYER = "WholesaleBuyer"
    CREW_LEAD = "CrewLead"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Season(TypedDict, total=False):
    id: str
    year: int
    booking_open_at: str
    booking_close_at: str
    harvest_window_start: str
    harvest_window_end: str
    shipping_window_start: str
    shipping_window_end: str
    posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Block(TypedDict, total=False):
    id: str
    season_id: str
    block_code: str
    acreage: float
    ucut_designated: bool
    rotation_state: str
    created_at: str
    updated_at: str
    version: int


class CropLot(TypedDict, total=False):
    id: str
    block_id: str
    species: str
    planted_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StandBucket(TypedDict, total=False):
    id: str
    crop_lot_id: str
    height_class: str
    baseline_count: int
    standing_count: int
    reserved_count: int
    tagged_active_count: int
    cut_cumulative: int
    culled_cumulative: int
    ucut_sold_cumulative: int
    consigned_cumulative: int
    available_count: int
    last_shrink_delta: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InventorySurvey(TypedDict, total=False):
    id: str
    crop_lot_id: str
    surveyed_counts: Dict[str, int]
    status: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuyerAccount(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    standing: str
    exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class WholesaleOrder(TypedDict, total=False):
    id: str
    season_id: str
    buyer_account_id: str
    species: str
    height_class: str
    quantity: int
    unit_price_cents: int
    allocated_qty: int
    invoice_subtotal_cents: Optional[int]
    discount_pct_applied: Optional[float]
    invoice_discount_cents: Optional[int]
    invoice_total_cents: Optional[int]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    order_id: str
    bucket_id: str
    quantity: int
    cut_qty: int
    loaded_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    season_id: str
    crew_code: str
    size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestTicket(TypedDict, total=False):
    id: str
    crew_id: str
    block_id: str
    work_date: str
    hours_worked: float
    lines: List[Dict[str, Any]]
    piece_total_cents: int
    hourly_floor_cents: int
    gross_pay_cents: int
    pay_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict, total=False):
    id: str
    season_id: str
    carrier_name: str
    capacity_units: int
    pickup_window_start: str
    pickup_window_end: str
    lines: List[Dict[str, Any]]
    total_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict, total=False):
    id: str
    season_id: str
    bucket_id: str
    lot_name: str
    quantity: int
    unit_price_cents: int
    max_return_pct: float
    delivered_count: Optional[int]
    returned_count: int
    provisional_settlement_cents: Optional[int]
    final_settlement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class UcutTag(TypedDict, total=False):
    id: str
    block_id: str
    bucket_id: str
    customer_name: str
    price_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CullRecord(TypedDict, total=False):
    id: str
    bucket_id: str
    count: int
    reason: str
    created_at: str
    updated_at: str
    version: int


class ReplantPlan(TypedDict, total=False):
    id: str
    block_id: str
    species: str
    planned_count: int
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    created_crop_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocateResult(TypedDict, total=False):
    order_id: str
    allocated_now: int
    allocated_total: int
    allocation_ids: List[str]
    order_status: str
    order_version: int
