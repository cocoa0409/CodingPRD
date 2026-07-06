"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this system carries the common system-managed fields
id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status / enum types ──────────────────────────────────────────────

class UserRole(str, Enum):
    HALL_MANAGER = "HallManager"
    VENDOR = "Vendor"
    HEALTH_INSPECTOR = "HealthInspector"
    POS_OPERATOR = "POSOperator"


class VendorStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    ROUTED = "ROUTED"
    ACCEPTED = "ACCEPTED"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"


class SeatingStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class StallPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


# ─── Entity TypedDicts (all carry common fields) ──────────────────────

class FoodHall(TypedDict):
    id: str
    name: str
    total_seating_capacity: int
    common_area_capacity: int
    hall_open_minutes: int
    hall_close_minutes: int
    event_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Stall(TypedDict):
    id: str
    food_hall_id: str
    stall_code: str
    size_sqft: int
    open_minutes: int
    close_minutes: int
    operational_posture: str
    current_lease_id: Optional[str]
    current_vendor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    stall_id: str
    vendor_id: str
    start_date: str
    end_date: str
    base_rent_cents: int
    percentage_rate: float
    natural_breakpoint_cents: int
    rent_cap_cents: int
    security_deposit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HealthPermit(TypedDict):
    id: str
    stall_id: str
    permit_number: str
    issued_on: Optional[str]
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    stall_id: str
    scheduled_for: str
    conducted_at: Optional[str]
    score: Optional[int]
    result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    food_hall_id: str
    stall_id: str
    gross_amount_cents: int
    item_count: int
    placed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SeatingAllocation(TypedDict):
    id: str
    food_hall_id: str
    order_id: Optional[str]
    seats: int
    start_time: str
    end_time: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketingEvent(TypedDict):
    id: str
    food_hall_id: str
    name: str
    start_time: str
    end_time: str
    reserved_capacity: int
    expected_footfall: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    lease_id: str
    period_start: str
    period_end: str
    gross_sales_cents: int
    base_rent_charged_cents: int
    percentage_rent_cents: int
    total_rent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
