"""Domain types: entity TypedDicts, status enums, role enum.

All names and fields mirror the Catering Commissary & Event Staffing PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Value enums (input fields)
# --------------------------------------------------------------------------
class Unit(str, Enum):
    GRAM = "GRAM"
    ML = "ML"
    EACH = "EACH"


class MenuCategory(str, Enum):
    ENTREE = "ENTREE"
    SIDE = "SIDE"
    BEVERAGE = "BEVERAGE"
    DESSERT = "DESSERT"


class AssetType(str, Enum):
    CHAFER = "CHAFER"
    LINEN = "LINEN"
    TABLE = "TABLE"
    GLASSWARE = "GLASSWARE"


class StaffRole(str, Enum):
    SERVER = "SERVER"
    BARTENDER = "BARTENDER"
    CHEF = "CHEF"


# --------------------------------------------------------------------------
# Lifecycle status enums
# --------------------------------------------------------------------------
class EventOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    PACKED = "PACKED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    ACTUALIZED = "ACTUALIZED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class QuoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class RentalReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class StaffAssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    ADMIN = "Admin"
    KITCHEN_MANAGER = "KitchenManager"
    SALES_MANAGER = "SalesManager"
    EVENT_CAPTAIN = "EventCaptain"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields:true entities carry id + created_at + updated_at + version.
# RecipeLine (common_fields:false) carries ONLY id + created_at.
# --------------------------------------------------------------------------
class Ingredient(TypedDict):
    id: str
    name: str
    unit: str
    unit_cost_cents: int
    on_hand_qty: float
    committed_qty: float
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    name: str
    category: str
    sell_price_cents_per_portion: int
    portion_food_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class RecipeLine(TypedDict):
    id: str
    menu_item_id: str
    ingredient_id: str
    qty_per_portion: float
    created_at: str
    # NOTE: append-only — no updated_at, no version.


class Station(TypedDict):
    id: str
    name: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict):
    id: str
    name: str
    asset_type: str
    total_units: int
    rental_price_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    name: str
    staff_role: str
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class EventOrder(TypedDict):
    id: str
    guest_count: int
    event_start: str
    event_end: str
    venue_address: str
    service_charge_pct: float
    gratuity_pct: float
    delivery_vehicle: Optional[str]
    delivery_depart_time: Optional[str]
    status: str
    actual_guest_count: Optional[int]
    actual_labor_total_cents: int
    actual_food_revenue_cents: Optional[int]
    actual_food_cost_cents: Optional[int]
    actual_rental_cents: Optional[int]
    actual_service_charge_cents: Optional[int]
    actual_gratuity_cents: Optional[int]
    actual_grand_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    event_order_id: str
    menu_item_id: str
    portions_per_guest: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    event_order_id: str
    status: str
    guest_count_snapshot: int
    food_revenue_cents: int
    food_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    event_order_id: str
    station_id: str
    menu_item_id: str
    portions: int
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalReservation(TypedDict):
    id: str
    event_order_id: str
    equipment_item_id: str
    qty: int
    out_time: str
    return_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    event_order_id: str
    staff_member_id: str
    staff_role: str
    shift_start: str
    shift_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    scheduled_labor_cents: int
    actual_labor_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
