"""Domain types for the Campus Shuttle Dispatch API.

Entity TypedDicts, status enums, and role enum. Field names mirror the
PRD verbatim. Common-fields entities (PRD §2.4) carry id + created_at +
updated_at + version; append-only entities (RouteVersion, RidershipRecord,
DelayEvent, AuditLog) carry only id + created_at and intentionally OMIT
updated_at and version.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    EMPLOYEE = "Employee"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StopStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    OFFSHELF = "OFFSHELF"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class VehicleType(str, Enum):
    STANDARD = "STANDARD"
    ELECTRIC = "ELECTRIC"
    SHUTTLE_VAN = "SHUTTLE_VAN"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class RunSheetStatus(str, Enum):
    PLANNED = "PLANNED"
    BOARDING = "BOARDING"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PayerMode(str, Enum):
    SELF_PAY = "SELF_PAY"
    DEPARTMENT_PAID = "DEPARTMENT_PAID"


class CheckInMethod(str, Enum):
    QR = "QR"
    CARD = "CARD"
    FACE = "FACE"


class DelayCause(str, Enum):
    TRAFFIC = "TRAFFIC"
    BREAKDOWN = "BREAKDOWN"
    WEATHER = "WEATHER"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class PayerScope(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    DEPARTMENT = "DEPARTMENT"


class StopAmenity(str, Enum):
    LIGHTING = "LIGHTING"
    SEATING = "SEATING"
    USB = "USB"
    DISPLAY = "DISPLAY"
    RAMP = "RAMP"


class AuditEventType(str, Enum):
    RESERVATION_CREATED = "RESERVATION_CREATED"
    RESERVATION_CANCELLED = "RESERVATION_CANCELLED"
    RESERVATION_CHECKED_IN = "RESERVATION_CHECKED_IN"
    RESERVATION_NO_SHOW = "RESERVATION_NO_SHOW"
    DELAY_REPORTED = "DELAY_REPORTED"
    SUBSTITUTE_DISPATCHED = "SUBSTITUTE_DISPATCHED"
    ROUTE_PUBLISHED = "ROUTE_PUBLISHED"
    BILL_REFUNDED = "BILL_REFUNDED"


class AuditSubjectType(str, Enum):
    RESERVATION = "Reservation"
    RUN_SHEET = "RunSheet"
    ROUTE = "Route"
    MONTHLY_BILL = "MonthlyBill"
    DELAY_EVENT = "DelayEvent"


# ---------------------------------------------------------------------------
# Common-fields entities (PRD §2.4: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Route(TypedDict, total=False):
    id: str
    code: str
    name: str
    start_stop_id: str
    end_stop_id: str
    intermediate_stop_ids: List[str]
    status: str
    version_number: int
    peak_frequency_minutes: int
    offpeak_frequency_minutes: int
    peak_windows: List[List[str]]
    estimated_distance_km: float
    estimated_duration_minutes: int
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict, total=False):
    id: str
    code: str
    name: str
    latitude: float
    longitude: float
    has_shelter: bool
    amenities: List[str]
    capacity_reference: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    plate_number: str
    seat_capacity: int
    vehicle_type: str
    status: str
    maintenance_window_start: Optional[str]
    maintenance_window_end: Optional[str]
    last_run_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    license_expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RunSheet(TypedDict, total=False):
    id: str
    route_id: str
    route_version_number: int
    scheduled_date: str
    scheduled_departure: str
    scheduled_arrival: str
    assigned_vehicle_id: Optional[str]
    assigned_driver_id: str
    substitute_vehicle_id: Optional[str]
    status: str
    capacity_remaining: int
    completed_at: Optional[str]
    delay_minutes_accumulated: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    employee_id: str
    run_sheet_id: str
    boarding_stop_id: str
    alighting_stop_id: str
    status: str
    waitlist_position: Optional[int]
    payer_mode: str
    department_code: Optional[str]
    fare_cents: int
    no_show_penalty_points: int
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonthlyBill(TypedDict, total=False):
    id: str
    billing_month: str
    payer_scope: str
    payer_id: str
    status: str
    gross_cents: Optional[int]
    refund_cents: int
    net_cents: Optional[int]
    line_count: Optional[int]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / snapshot entities (PRD §2.4: id + created_at only)
# ---------------------------------------------------------------------------
class RouteVersion(TypedDict, total=False):
    id: str
    route_code: str
    version_number: int
    stop_sequence_snapshot: List[str]
    peak_frequency_minutes: int
    offpeak_frequency_minutes: int
    peak_windows: List[List[str]]
    published_at: str
    retired_at: Optional[str]
    created_at: str


class RidershipRecord(TypedDict, total=False):
    id: str
    reservation_id: Optional[str]
    run_sheet_id: str
    employee_id: str
    check_in_method: str
    boarded_stop_id: str
    alighted_stop_id: Optional[str]
    boarded_at: str
    alighted_at: Optional[str]
    created_at: str


class DelayEvent(TypedDict, total=False):
    id: str
    run_sheet_id: str
    cause: str
    delay_minutes: int
    affected_from_stop_id: str
    notification_dispatched: bool
    substitute_dispatched: bool
    reported_at: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    event_type: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    payload: dict
    created_at: str


__all__ = [
    "UserRole",
    "RouteStatus",
    "StopStatus",
    "VehicleStatus",
    "VehicleType",
    "DriverStatus",
    "RunSheetStatus",
    "ReservationStatus",
    "PayerMode",
    "CheckInMethod",
    "DelayCause",
    "BillStatus",
    "PayerScope",
    "StopAmenity",
    "AuditEventType",
    "AuditSubjectType",
    "Route",
    "Stop",
    "Vehicle",
    "Driver",
    "RunSheet",
    "Reservation",
    "MonthlyBill",
    "RouteVersion",
    "RidershipRecord",
    "DelayEvent",
    "AuditLog",
]
