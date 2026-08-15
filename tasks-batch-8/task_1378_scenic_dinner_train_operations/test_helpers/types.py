"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SCHEDULER = "Scheduler"
    MECHANIC = "Mechanic"
    STATION_AGENT = "StationAgent"
    CREW_MANAGER = "CrewManager"
    CATERING_MANAGER = "CateringManager"
    OPERATIONS_MANAGER = "OperationsManager"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class StockType(str, Enum):
    LOCOMOTIVE = "LOCOMOTIVE"
    COACH_CAR = "COACH_CAR"
    FIRST_CLASS_CAR = "FIRST_CLASS_CAR"
    DINING_CAR = "DINING_CAR"


class StockStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class WorkOrderScope(str, Enum):
    INSPECTION = "INSPECTION"
    REPAIR = "REPAIR"
    OVERHAUL = "OVERHAUL"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    REGULAR = "REGULAR"
    HOLIDAY = "HOLIDAY"


class ExcursionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    BOARDING = "BOARDING"
    OPERATED = "OPERATED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    WEATHER = "WEATHER"
    EVENT = "EVENT"
    OPERATOR = "OPERATOR"
    TRACK_RIGHTS_LOST = "TRACK_RIGHTS_LOST"


class ClassCode(str, Enum):
    LOCO = "LOCO"
    COACH = "COACH"
    FIRST_CLASS = "FIRST_CLASS"
    DINING = "DINING"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RAIN_CHECKED = "RAIN_CHECKED"
    NO_SHOW = "NO_SHOW"


class DiningService(str, Enum):
    EARLY = "EARLY"
    LATE = "LATE"


class CrewRole(str, Enum):
    ENGINEER = "ENGINEER"
    CONDUCTOR = "CONDUCTOR"
    CAR_HOST = "CAR_HOST"
    CHEF = "CHEF"
    SERVER = "SERVER"
    DOCENT = "DOCENT"


class CrewMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CrewAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    PROVISIONED = "PROVISIONED"


class RainCheckStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class RainCheckReason(str, Enum):
    WEATHER = "WEATHER"
    EVENT = "EVENT"
    TRACK_RIGHTS_LOST = "TRACK_RIGHTS_LOST"


class TrackRightsAgreement(TypedDict, total=False):
    id: str
    host_railroad_name: str
    subdivision_code: str
    valid_from: str
    valid_until: str
    max_trains_per_day: int
    min_slot_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatingSlot(TypedDict, total=False):
    id: str
    agreement_id: str
    service_date: str
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RollingStock(TypedDict, total=False):
    id: str
    unit_code: str
    stock_type: str
    seat_capacity: int
    table_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict, total=False):
    id: str
    stock_id: str
    window_start: str
    window_end: str
    scope: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Excursion(TypedDict, total=False):
    id: str
    title: str
    slot_id: str
    event_type: str
    surge_multiplier_bp: int
    service_date: str
    status: str
    cancel_reason: Optional[str]
    coach_seats_available: int
    first_class_seats_available: int
    dining_seats_available: int
    created_at: str
    updated_at: str
    version: int


class CarAssignment(TypedDict, total=False):
    id: str
    excursion_id: str
    stock_id: str
    class_code: str
    position: int
    effective_capacity: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    excursion_id: str
    customer_email: str
    class_code: str
    party_size: int
    dining_service: Optional[str]
    status: str
    expires_at: str
    unit_fare_cents: int
    total_price_cents: int
    paid_cents: int
    refund_cents: int
    dining_table_number: Optional[int]
    dining_car_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    name: str
    role: str
    is_volunteer: bool
    cert_expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    excursion_id: str
    crew_member_id: str
    position: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProvisioningManifest(TypedDict, total=False):
    id: str
    excursion_id: str
    status: str
    early_diner_count: int
    late_diner_count: int
    galley_load_units: int
    locked_at: Optional[str]
    actual_loaded_units: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RainCheck(TypedDict, total=False):
    id: str
    booking_id: str
    customer_email: str
    value_cents: int
    reason: str
    issued_on: str
    expires_on: str
    status: str
    redeemed_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
