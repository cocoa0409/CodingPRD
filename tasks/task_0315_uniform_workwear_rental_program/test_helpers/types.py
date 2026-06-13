"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Uniform & Workwear Rental Program PRD. Every primary entity in
this program is mutable and therefore carries the full common set
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    ROUTE_DRIVER = "RouteDriver"
    CLEANROOM_TECH = "CleanroomTech"


# ─── Status enums ─────────────────────────────────────────────────────────
class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    ON_HOLD = "ON_HOLD"


class RosterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RAMP_DOWN = "RAMP_DOWN"
    REMOVED = "REMOVED"


class GarmentCategory(str, Enum):
    SHIRT = "SHIRT"
    PANT = "PANT"
    JACKET = "JACKET"
    COVERALL = "COVERALL"


class LifecycleStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ASSIGNED = "ASSIGNED"
    RETIRED = "RETIRED"
    LOST = "LOST"


class WashLocation(str, Enum):
    AT_PLANT = "AT_PLANT"
    AT_CUSTOMER = "AT_CUSTOMER"
    IN_SOIL = "IN_SOIL"
    IN_WASH = "IN_WASH"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RETURNED = "RETURNED"
    LOST = "LOST"
    DAMAGED = "DAMAGED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"


class ChargeType(str, Enum):
    RENTAL = "RENTAL"
    SHORTAGE = "SHORTAGE"
    LOSS = "LOSS"
    DAMAGE = "DAMAGE"
    EMBLEM_SETUP = "EMBLEM_SETUP"


class ServiceDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


class ShirtSize(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "XXL"


# ─── Entity TypedDicts (all common_fields: true) ──────────────────────────
class Account(TypedDict):
    id: str
    legal_name: str
    service_day: str
    shortage_grace_units: int
    billing_status: str
    outstanding_cents: int
    active_wearer_count: int
    created_at: str
    updated_at: str
    version: int


class Wearer(TypedDict):
    id: str
    account_id: str
    full_name: str
    shirt_size: str
    pant_size: int
    roster_status: str
    assigned_garment_count: int
    locker_label: str
    created_at: str
    updated_at: str
    version: int


class GarmentType(TypedDict):
    id: str
    sku: str
    category: str
    weekly_rate_cents: int
    replacement_cost_cents: int
    emblem_setup_cents: int
    created_at: str
    updated_at: str
    version: int


class Garment(TypedDict):
    id: str
    account_id: str
    garment_type_id: str
    tag_code: str
    lifecycle_status: str
    wash_location: str
    emblem_text: Optional[str]
    soil_strikes: int
    cycled_through_wash_this_visit: bool
    wash_station_id: Optional[str]
    slot_start_min: Optional[int]
    slot_end_min: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WashStation(TypedDict):
    id: str
    station_code: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    garment_id: str
    wearer_id: str
    account_id: str
    status: str
    assigned_at_iso: str
    closed_at_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    route_code: str
    service_day: str
    driver_user_id: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    account_id: str
    stop_sequence: int
    window_start_min: int
    window_end_min: int
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    route_stop_id: str
    account_id: str
    week_index: int
    status: str
    expected_soil_count: int
    actual_soil_count: int
    provisional_charge_cents: int
    finalized_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceCharge(TypedDict):
    id: str
    service_visit_id: Optional[str]
    account_id: str
    charge_type: str
    amount_cents: int
    paid: bool
    created_at: str
    updated_at: str
    version: int
