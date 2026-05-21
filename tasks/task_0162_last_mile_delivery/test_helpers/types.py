"""Domain types — entity TypedDicts, status enums, and the role enum.

Derived from PRD §2.4 (common resource properties), §2.6 (hazmat),
§2.7 (signature / driver-release), and §3 (workflows). Entities that
PRD §2.4 calls out as "intentionally lightweight" — Address, RouteStop,
DeliveryAttempt — carry only id + created_at and intentionally OMIT
updated_at and version. The synthetic Clock entity exposes only `now`.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums — PRD §3.3, §3.4, §3.5
# ---------------------------------------------------------------------------
class ParcelStatus(str, Enum):
    INDUCTED = "INDUCTED"
    IN_TRANSIT_HUB = "IN_TRANSIT_HUB"
    SORTED = "SORTED"
    ON_VEHICLE = "ON_VEHICLE"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    RETURNED_TO_SENDER = "RETURNED_TO_SENDER"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class DriverStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    ON_DUTY = "ON_DUTY"
    ON_ROUTE = "ON_ROUTE"
    RETURNED = "RETURNED"


class AppointmentStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class HazmatClass(str, Enum):
    NONE = "NONE"
    CLASS_2 = "CLASS_2"
    CLASS_3 = "CLASS_3"
    CLASS_4 = "CLASS_4"
    CLASS_8 = "CLASS_8"
    CLASS_9 = "CLASS_9"


class AttemptOutcome(str, Enum):
    DELIVERED_SIGNED = "DELIVERED_SIGNED"
    DRIVER_RELEASED = "DRIVER_RELEASED"
    NO_ONE_HOME = "NO_ONE_HOME"
    REFUSED = "REFUSED"
    ADDRESS_INVALID = "ADDRESS_INVALID"
    HAZMAT_BLOCKED = "HAZMAT_BLOCKED"


class LastAttemptOutcome(str, Enum):
    NONE = "NONE"
    DELIVERED_SIGNED = "DELIVERED_SIGNED"
    DRIVER_RELEASED = "DRIVER_RELEASED"
    NO_ONE_HOME = "NO_ONE_HOME"
    REFUSED = "REFUSED"
    ADDRESS_INVALID = "ADDRESS_INVALID"
    HAZMAT_BLOCKED = "HAZMAT_BLOCKED"


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DRIVER = "Driver"
    DISPATCHER = "Dispatcher"
    SORTING_HUB_OPERATOR = "SortingHubOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Common-fields entity TypedDicts — PRD §2.4 (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    phone: str
    default_address_id: Optional[str]
    driver_release_authorized: bool
    redelivery_attempts_used_30d: int
    created_at: str
    updated_at: str
    version: int


class TransitCenter(TypedDict, total=False):
    id: str
    code: str
    serviced_postal_prefixes: List[str]
    hazmat_certified: bool
    parcels_on_belt: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    badge_id: str
    home_center_id: str
    hazmat_endorsement: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict, total=False):
    id: str
    tracking_number: str
    customer_id: str
    destination_address_id: str
    origin_center_id: str
    weight_kg: float
    declared_value: float
    signature_required: bool
    hazmat_class: str
    time_window_start: str
    time_window_end: str
    status: str
    redelivery_attempts: int
    quoted_fee: float
    final_fee: Optional[float]
    last_attempt_outcome: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    center_id: str
    driver_id: str
    planned_date: str
    status: str
    total_distance_km: float
    stop_count: int
    hazmat_present: bool
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    parcel_id: str
    requested_window_start: str
    requested_window_end: str
    status: str
    fee_charged: float
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lightweight entities — PRD §2.4: "intentionally lightweight and carry
# only the id and created_at fields — both updated_at and version are
# absent from their representations."
# ---------------------------------------------------------------------------
class Address(TypedDict, total=False):
    id: str
    customer_id: str
    line1: str
    city: str
    postal_code: str
    latitude: float
    longitude: float
    residential: bool
    created_at: str


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    parcel_id: str
    sequence: int
    planned_arrival: str
    planned_departure: str
    status: str
    created_at: str


class DeliveryAttempt(TypedDict, total=False):
    id: str
    parcel_id: str
    route_stop_id: str
    driver_id: str
    attempted_at: str
    outcome: str
    signature_blob_ref: Optional[str]
    release_location: Optional[str]
    created_at: str


class Clock(TypedDict, total=False):
    now: str


__all__ = [
    "ParcelStatus",
    "RouteStatus",
    "RouteStopStatus",
    "DriverStatus",
    "AppointmentStatus",
    "HazmatClass",
    "AttemptOutcome",
    "LastAttemptOutcome",
    "UserRole",
    "Customer",
    "TransitCenter",
    "Driver",
    "Parcel",
    "Route",
    "Appointment",
    "Address",
    "RouteStop",
    "DeliveryAttempt",
    "Clock",
]
