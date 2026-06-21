"""Domain types: entity TypedDicts, status enums, role enum.

All field names, enum values, and the common-field set for each entity are
taken directly from the NEMT PRD (Sections 2 and 3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Ordered enumerations (PRD 2.7) ---

class Modality(str, Enum):
    AMBULATORY = "AMBULATORY"
    WHEELCHAIR = "WHEELCHAIR"
    STRETCHER = "STRETCHER"


class LevelOfService(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    BARIATRIC = "BARIATRIC"


# --- Status enums ---

class MemberEligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BrokerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DriverStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_TRIP = "ON_TRIP"
    OFFLINE = "OFFLINE"


class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CLAIMED = "CLAIMED"
    ENCOUNTERED = "ENCOUNTERED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class LegDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    RETURN = "RETURN"


class LegStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    PICKED_UP = "PICKED_UP"
    DROPPED_OFF = "DROPPED_OFF"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RELEASED = "RELEASED"


class StandingOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    DENIED = "DENIED"


class EncounterStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"


class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    BROKER = "Broker"
    DRIVER = "Driver"
    AUDITOR = "Auditor"


# --- Entity TypedDicts ---

# common_fields: true — id + created_at + updated_at + version
class Member(TypedDict):
    id: str
    medicaid_id: str
    full_name: str
    mobility_level: str
    home_county: str
    eligibility_status: str
    noshow_strike_count: int
    standing_orders_paused: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only coverage record: id + created_at ONLY
class EligibilitySpan(TypedDict):
    id: str
    member_id: str
    level_of_service: str
    coverage_start: str
    coverage_end: str
    voided: bool
    created_at: str


# common_fields: true
class Broker(TypedDict):
    id: str
    name: str
    covered_counties: List[str]
    max_modality: str
    free_deadhead_miles: float
    deadhead_rate_cents_per_mile: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Driver(TypedDict):
    id: str
    broker_id: str
    full_name: str
    vehicle_modality: str
    base_county: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable pricing configuration: id + created_at ONLY
class RateSchedule(TypedDict):
    id: str
    modality: str
    base_fare_cents: int
    loaded_rate_cents_per_mile: int
    dwell_free_minutes: int
    dwell_cents_per_minute: int
    created_at: str


# common_fields: true
class TripRequest(TypedDict):
    id: str
    member_id: str
    standing_order_id: Optional[str]
    modality: str
    requested_level_of_service: str
    appointment_at: str
    is_round_trip: bool
    return_is_will_call: bool
    trip_status: str
    billing_status: str
    assigned_broker_id: Optional[str]
    assigned_driver_id: Optional[str]
    scheduled_loaded_miles: float
    claimed_cost_cents: int
    encounter_cost_cents: int
    reconciliation_variance_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Leg(TypedDict):
    id: str
    trip_id: str
    direction: str
    is_will_call: bool
    leg_status: str
    ready_called_at: Optional[str]
    arrived_at: Optional[str]
    picked_up_at: Optional[str]
    dropped_off_at: Optional[str]
    odometer_loaded_miles: float
    dwell_minutes: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Assignment(TypedDict):
    id: str
    trip_id: str
    broker_id: str
    driver_id: str
    status: str
    deadhead_miles: float
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class StandingOrder(TypedDict):
    id: str
    member_id: str
    modality: str
    level_of_service: str
    weekday_mask: int
    appointment_time_utc: str
    scheduled_loaded_miles: float
    horizon_through: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Claim(TypedDict):
    id: str
    trip_id: str
    broker_id: str
    billed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Encounter(TypedDict):
    id: str
    trip_id: str
    captured_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
