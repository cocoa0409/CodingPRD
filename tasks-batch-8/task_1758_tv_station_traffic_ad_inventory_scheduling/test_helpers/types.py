"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SALES_REP = "SalesRep"
    TRAFFIC_MANAGER = "TrafficManager"
    COPY_COORDINATOR = "CopyCoordinator"
    BILLING_CLERK = "BillingClerk"
    STATION_ADMIN = "StationAdmin"


class ProductCategory(str, Enum):
    AUTOMOTIVE = "AUTOMOTIVE"
    RETAIL = "RETAIL"
    RESTAURANT = "RESTAURANT"
    PHARMA = "PHARMA"
    FINANCE = "FINANCE"
    POLITICAL = "POLITICAL"
    OTHER = "OTHER"


class DaypartCode(str, Enum):
    EARLY_MORNING = "EARLY_MORNING"
    DAYTIME = "DAYTIME"
    EARLY_NEWS = "EARLY_NEWS"
    PRIME = "PRIME"
    LATE_NEWS = "LATE_NEWS"
    LATE_FRINGE = "LATE_FRINGE"
    OVERNIGHT = "OVERNIGHT"


class AvailWeekStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISED = "REVISED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class CopyInstructionStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    EXPIRED = "EXPIRED"


class SpotStatus(str, Enum):
    PENDING_PLACEMENT = "PENDING_PLACEMENT"
    SCHEDULED = "SCHEDULED"
    PREEMPTED = "PREEMPTED"
    MAKE_GOOD_OFFERED = "MAKE_GOOD_OFFERED"
    AIRED = "AIRED"
    CANCELLED = "CANCELLED"


class SpotClass(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    POLITICAL = "POLITICAL"


class PreemptReason(str, Enum):
    NONE = "NONE"
    POLITICAL_PRIORITY = "POLITICAL_PRIORITY"
    OVERSOLD = "OVERSOLD"
    NEWS_OVERRIDE = "NEWS_OVERRIDE"


class LogDayStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    RECONCILED = "RECONCILED"


# --- Entities carrying the common fields id/created_at/updated_at/version (PRD §2.4) ---


class Advertiser(TypedDict, total=False):
    id: str
    name: str
    agency_name: str
    product_category: str
    credit_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    title: str
    daypart_code: str
    airs_weekday: int
    start_time_local: str
    duration_minutes: int
    rating_estimate: float
    is_political_window: bool
    created_at: str
    updated_at: str
    version: int


class AvailWeek(TypedDict, total=False):
    id: str
    week_start_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailUnit(TypedDict, total=False):
    id: str
    avail_week_id: str
    program_id: str
    air_date: str
    break_position: int
    total_seconds: int
    reserved_political_seconds: int
    booked_commercial_seconds: int
    booked_political_seconds: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    advertiser_id: str
    flight_start_date: str
    flight_end_date: str
    status: str
    gross_budget_cents: int
    revision_no: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    program_id: str
    weeks_requested: int
    spots_per_week: int
    spot_length_seconds: int
    gross_rate_cents: int
    guaranteed_rating: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CopyInstruction(TypedDict, total=False):
    id: str
    advertiser_id: str
    length_seconds: int
    rotation_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Spot(TypedDict, total=False):
    id: str
    order_line_id: str
    avail_unit_id: Optional[str]
    copy_instruction_id: Optional[str]
    spot_class: str
    scheduled_air_date: Optional[str]
    status: str
    preempt_reason: str
    make_good_of_spot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LogDay(TypedDict, total=False):
    id: str
    avail_week_id: str
    log_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): carries id and created_at ONLY — no updated_at, no version.
class AsRunEntry(TypedDict, total=False):
    id: str
    created_at: str
    log_day_id: str
    spot_id: str
    aired: bool
    actual_rating: float


class PostBuyReport(TypedDict, total=False):
    order_id: str
    lines: List[dict]
    discrepancy_credit_cents: int
    shortfall_credit_cents: int
    order_credit_cents: int
