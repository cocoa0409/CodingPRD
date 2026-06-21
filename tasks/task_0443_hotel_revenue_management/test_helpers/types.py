"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the Hotel Revenue Management API contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    REVENUE_MANAGER = "RevenueManager"
    GROUP_SALES_MANAGER = "GroupSalesManager"
    CHANNEL_MANAGER = "ChannelManager"
    ANALYST = "Analyst"


# --- Status / enum value sets ---
class RateClass(str, Enum):
    BAR = "BAR"
    CORPORATE = "CORPORATE"
    ADVANCE_PURCHASE = "ADVANCE_PURCHASE"
    PACKAGE = "PACKAGE"


class RatePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RateDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class GroupBlockStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    COMMITTED = "COMMITTED"
    CANCELLED = "CANCELLED"
    LOST = "LOST"


class TransientReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    CHECKED_OUT = "CHECKED_OUT"


class Channel(str, Enum):
    DIRECT = "DIRECT"
    OTA_A = "OTA_A"
    OTA_B = "OTA_B"
    GDS = "GDS"


class ParityStatus(str, Enum):
    IN_PARITY = "IN_PARITY"
    OUT_OF_PARITY = "OUT_OF_PARITY"


class GroupRecommendation(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


# --- Entity TypedDicts (mutable entities carry id + created_at + updated_at + version) ---
class Property(TypedDict):
    id: str
    name: str
    total_rooms: int
    overbooking_limit_pct: float
    currency: str
    occupancy_pct: float
    adr: float
    revpar: float
    created_at: str
    updated_at: str
    version: int


class RoomType(TypedDict):
    id: str
    property_id: str
    code: str
    name: str
    physical_rooms: int
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    room_type_id: str
    rate_class: str
    is_master_bar: bool
    min_los: int
    max_los: int
    base_rate: float
    floor_rate: float
    ceiling_rate: float
    status: str
    published_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class InventoryDay(TypedDict):
    id: str
    room_type_id: str
    stay_date: str
    physical_capacity: int
    group_held_rooms: int
    transient_sold_rooms: int
    transient_revenue: float
    rooms_sold: int
    rooms_available: int
    created_at: str
    updated_at: str
    version: int


class RateDecision(TypedDict):
    id: str
    rate_plan_id: str
    stay_date: str
    status: str
    requested_rate: float
    yielded_rate: Optional[float]
    applied_yield_rule_id: Optional[str]
    last_room_premium_applied: bool
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class YieldRule(TypedDict):
    id: str
    property_id: str
    name: str
    occupancy_threshold_pct: float
    adjustment_pct: float
    priority: int
    enabled: bool
    created_at: str
    updated_at: str
    version: int


class GroupBlock(TypedDict):
    id: str
    room_type_id: str
    group_name: str
    arrival_date: str
    nights: int
    rooms_per_night: int
    offered_rate: float
    status: str
    displacement_cost: Optional[float]
    recommendation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChannelMapping(TypedDict):
    id: str
    rate_plan_id: str
    channel: str
    markup_pct: float
    manual_rate_override: Optional[float]
    parity_status: str
    channel_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TransientReservation(TypedDict):
    id: str
    room_type_id: str
    rate_plan_id: str
    arrival_date: str
    nights: int
    rooms: int
    status: str
    booked_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable snapshot, carries ONLY id + created_at (no updated_at, no version)
class CompetitorRate(TypedDict):
    id: str
    property_id: str
    competitor_name: str
    stay_date: str
    shopped_rate: float
    shopped_at: str
    created_at: str


# --- Forecast computed-read payload (not a persisted entity) ---
class ForecastResult(TypedDict):
    forecast_final_sold: int
    forecast_occupancy_pct: float
    method: str
