"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource in this API carries the common fields id, created_at,
updated_at, and version (see PRD §2.4), so every entity TypedDict lists them.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    AIRPORT_AUTHORITY = "AirportAuthority"
    OPERATOR = "Operator"
    CURB_COORDINATOR = "CurbCoordinator"


class OperatorType(str, Enum):
    TNC = "TNC"
    TAXI = "TAXI"
    LIMO = "LIMO"
    SHUTTLE = "SHUTTLE"


class OperatorStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class OperatorSuspendedReason(str, Enum):
    ADMIN = "ADMIN"
    PENALTY_THRESHOLD = "PENALTY_THRESHOLD"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class QueueEntryStatus(str, Enum):
    WAITING = "WAITING"
    RELEASED = "RELEASED"
    EXITED = "EXITED"
    CANCELLED = "CANCELLED"


class CurbAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class TripKind(str, Enum):
    PICKUP = "PICKUP"
    DEADHEAD = "DEADHEAD"


class TripStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    PICKED_UP = "PICKED_UP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class ViolationType(str, Enum):
    STAGING = "STAGING"
    CURB = "CURB"
    AVI_MISMATCH = "AVI_MISMATCH"
    NO_DECAL = "NO_DECAL"
    WAV_SHORTFALL = "WAV_SHORTFALL"


class ViolationSource(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    DISMISSED = "DISMISSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class Operator(TypedDict):
    id: str
    legal_name: str
    operator_type: str
    contact_email: str
    wheelchair_pledge_pct: float
    status: str
    suspended_reason: Optional[str]
    rolling_penalty_points: int
    lifetime_penalty_points: int
    outstanding_fees_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    operator_id: str
    plate: str
    is_wheelchair_accessible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    vehicle_id: str
    avi_tag_id: str
    decal_number: Optional[str]
    valid_from: str
    valid_until: str
    fee_paid_cents: int
    permit_status: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StagingLot(TypedDict):
    id: str
    name: str
    geofence_center_lat: float
    geofence_center_lng: float
    geofence_radius_m: float
    capacity: int
    created_at: str
    updated_at: str
    version: int


class QueueEntry(TypedDict):
    id: str
    staging_lot_id: str
    vehicle_id: str
    position: int
    status: str
    enter_ts: str
    exit_ts: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CurbZone(TypedDict):
    id: str
    name: str
    terminal: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class CurbAssignment(TypedDict):
    id: str
    curb_zone_id: str
    trip_id: str
    start_ts: str
    end_ts: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    operator_id: str
    vehicle_id: str
    trip_kind: str
    is_wheelchair_trip: bool
    status: str
    dispatch_ts: str
    pickup_ts: Optional[str]
    complete_ts: Optional[str]
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    settlement_statement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    operator_id: str
    trip_id: Optional[str]
    violation_type: str
    source: str
    penalty_points: int
    fine_cents: int
    status: str
    assessed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict):
    id: str
    operator_id: str
    period_year: int
    period_month: int
    status: str
    gross_fees_cents: int
    admin_fee_cents: int
    wav_incentive_credit_cents: int
    net_due_cents: int
    total_trip_count: int
    wav_trip_count: int
    closed_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
