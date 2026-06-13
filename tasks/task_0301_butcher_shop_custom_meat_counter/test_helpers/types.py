"""Domain types: entity TypedDicts, status enums, role enum.

All names and fields follow the PRD (the Butcher Shop & Custom Meat Counter API).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    COUNTER_CLERK = "CounterClerk"
    BUTCHER = "Butcher"
    SHIFT_MANAGER = "ShiftManager"
    SAFETY_OFFICER = "SafetyOfficer"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    WHOLESALE = "WHOLESALE"


class Species(str, Enum):
    BEEF = "BEEF"
    PORK = "PORK"
    LAMB = "LAMB"
    POULTRY = "POULTRY"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    AGING = "AGING"
    ON_HOLD = "ON_HOLD"
    DEPLETED = "DEPLETED"
    DISCARDED = "DISCARDED"


class LockerStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    QUARANTINED = "QUARANTINED"


class ShareStatus(str, Enum):
    OPEN = "OPEN"
    FULLY_CLAIMED = "FULLY_CLAIMED"
    BROKEN_DOWN = "BROKEN_DOWN"
    CANCELLED = "CANCELLED"


class ClaimFraction(str, Enum):
    QUARTER = "QUARTER"
    HALF = "HALF"


class ClaimStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class OrderKind(str, Enum):
    STANDARD = "STANDARD"
    HOLIDAY = "HOLIDAY"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    FILLED = "FILLED"
    SHORT_FILLED = "SHORT_FILLED"
    CANCELLED = "CANCELLED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    DRAWN = "DRAWN"
    SHORTED = "SHORTED"


class DrawStatus(str, Enum):
    COMMITTED = "COMMITTED"
    REVERTED = "REVERTED"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    PRODUCED = "PRODUCED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Entities carrying the full system field set (id, created_at, updated_at,
# version) are the primary resources. TempReading is append-only and carries
# only id + created_at.
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    full_name: str
    phone: str
    loyalty_tier: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class CutType(TypedDict):
    id: str
    code: str
    species: str
    base_price_cents_per_kg: int
    is_grind: bool
    requires_dry_age: bool
    created_at: str
    updated_at: str
    version: int


class PricingPolicy(TypedDict):
    id: str
    shrink_pct_whole_cut: float
    shrink_pct_grind: float
    preferred_discount_pct: float
    wholesale_discount_pct: float
    bulk_threshold_g: int
    bulk_extra_discount_pct: float
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    cut_type_id: str
    source_share_id: Optional[str]
    received_weight_g: int
    remaining_weight_g: int
    lot_status: str
    locker_id: Optional[str]
    aging_started_at: Optional[str]
    aging_target_days: int
    created_at: str
    updated_at: str
    version: int


class DryAgeLocker(TypedDict):
    id: str
    name: str
    capacity_g: int
    occupied_g: int
    min_temp_c: float
    max_temp_c: float
    locker_status: str
    last_excursion_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only log: id + created_at only (no updated_at, no version).
class TempReading(TypedDict):
    id: str
    locker_id: str
    temp_c: float
    reading_at: str
    in_band: bool
    triggered_quarantine: bool
    created_at: str


class AnimalShare(TypedDict):
    id: str
    species: str
    carcass_weight_g: int
    deposit_cents: int
    claimed_fraction_x4: int
    remaining_carcass_g: int
    share_status: str
    created_at: str
    updated_at: str
    version: int


class ShareClaim(TypedDict):
    id: str
    animal_share_id: str
    customer_id: str
    fraction: str
    deposit_paid_cents: int
    claim_status: str
    created_at: str
    updated_at: str
    version: int


class CustomOrder(TypedDict):
    id: str
    customer_id: str
    order_kind: str
    pickup_date: Optional[str]
    holiday_window_id: Optional[str]
    deposit_cents: int
    estimated_total_cents: int
    final_total_cents: Optional[int]
    order_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    custom_order_id: str
    cut_type_id: str
    ordered_weight_g: int
    catch_weight_g: Optional[int]
    est_line_cents: int
    final_line_cents: Optional[int]
    drawn_lot_id: Optional[str]
    line_status: str
    created_at: str
    updated_at: str
    version: int


class LotDraw(TypedDict):
    id: str
    inventory_lot_id: str
    order_line_id: Optional[str]
    batch_input_id: Optional[str]
    weight_g: int
    draw_status: str
    created_at: str
    updated_at: str
    version: int


class SausageBatch(TypedDict):
    id: str
    recipe_name: str
    output_cut_type_id: str
    planned_output_g: int
    actual_yield_g: Optional[int]
    batch_status: str
    created_at: str
    updated_at: str
    version: int


class BatchInput(TypedDict):
    id: str
    sausage_batch_id: str
    inventory_lot_id: str
    weight_g: int
    created_at: str
    updated_at: str
    version: int


class HolidayWindow(TypedDict):
    id: str
    name: str
    pickup_date: str
    capacity_g: int
    committed_g: int
    cutoff_at: str
    created_at: str
    updated_at: str
    version: int
