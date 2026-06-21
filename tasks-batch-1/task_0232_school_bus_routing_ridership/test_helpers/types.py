"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the School Bus Routing & Ridership PRD (§2.4, §3).
Append-only event records (TapEvent, ParentNotification) carry ONLY id and
created_at — no updated_at, no version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TRANSPORT_ADMIN = "TransportAdmin"
    PARENT = "Parent"
    DRIVER = "Driver"


# ---------------------------------------------------------------------------
# Status / enum value sets (PRD §3)
# ---------------------------------------------------------------------------
class RoutePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EligibilityBasis(str, Enum):
    PENDING = "PENDING"
    DISTANCE = "DISTANCE"
    HAZARD = "HAZARD"
    NONE = "NONE"


class DenialReason(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    ROUTE_FULL = "ROUTE_FULL"
    WHEELCHAIR_FULL = "WHEELCHAIR_FULL"
    ROUTE_NOT_OPEN = "ROUTE_NOT_OPEN"


class DriverStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DUTY = "ON_DUTY"


class AssignmentRole(str, Enum):
    PRIMARY = "PRIMARY"
    SUBSTITUTE = "SUBSTITUTE"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class BusTripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BOARDING = "BOARDING"
    IN_TRANSIT = "IN_TRANSIT"
    INCIDENT_HOLD = "INCIDENT_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TapDirection(str, Enum):
    TAP_ON = "TAP_ON"
    TAP_OFF = "TAP_OFF"


class NotificationKind(str, Enum):
    TAP_ON = "TAP_ON"
    TAP_OFF = "TAP_OFF"
    MISSED_BUS = "MISSED_BUS"
    INCIDENT = "INCIDENT"
    APPLICATION_DECISION = "APPLICATION_DECISION"


class MissedBusStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class MissedBusResolution(str, Enum):
    PARENT_PICKUP = "PARENT_PICKUP"
    REBOARDED_NEXT_TRIP = "REBOARDED_NEXT_TRIP"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true carry the full quartet (PRD §2.4)
# ---------------------------------------------------------------------------
class District(TypedDict):
    id: str
    name: str
    school_lat: float
    school_lng: float
    walk_threshold_miles: float
    hazard_override_enabled: bool
    missed_bus_grace_minutes: int
    service_day_index: int
    active_route_count: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    district_id: str
    name: str
    seat_capacity: int
    wheelchair_capacity: int
    posture: str
    assigned_rider_count: int
    assigned_wheelchair_count: int
    open_incident: bool
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict):
    id: str
    route_id: str
    label: str
    lat: float
    lng: float
    sequence: int
    scheduled_departure: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    district_id: str
    parent_id: str
    full_name: str
    grade: int
    home_lat: float
    home_lng: float
    hazard_zone: bool
    special_needs: bool
    rfid_uid: str
    home_distance_miles: float
    created_at: str
    updated_at: str
    version: int


class RidershipApplication(TypedDict):
    id: str
    district_id: str
    student_id: str
    requested_route_id: str
    requested_stop_id: str
    eligibility_basis: str
    status: str
    assigned_route_id: Optional[str]
    assigned_stop_id: Optional[str]
    review_round: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    district_id: str
    full_name: str
    is_substitute: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DriverAssignment(TypedDict):
    id: str
    route_id: str
    driver_id: str
    role: str
    replaces_assignment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BusTrip(TypedDict):
    id: str
    route_id: str
    driver_assignment_id: str
    service_day_index: int
    status: str
    current_stop_sequence: int
    last_lat: Optional[float]
    last_lng: Optional[float]
    eta_next_stop_minutes: Optional[float]
    onboard_count: int
    incident_count: int
    created_at: str
    updated_at: str
    version: int


class MissedBusReport(TypedDict):
    id: str
    district_id: str
    student_id: str
    bus_trip_id: str
    reported_stop_sequence: int
    status: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only event records — id + created_at ONLY (PRD §2.4)
# ---------------------------------------------------------------------------
class TapEvent(TypedDict):
    id: str
    bus_trip_id: str
    student_id: str
    rfid_uid: str
    direction: str
    stop_sequence: int
    created_at: str


class ParentNotification(TypedDict):
    id: str
    district_id: str
    parent_id: str
    student_id: str
    bus_trip_id: Optional[str]
    kind: str
    payload: dict
    created_at: str
