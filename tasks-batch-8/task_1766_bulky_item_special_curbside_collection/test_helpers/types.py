"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    RESIDENT = "Resident"
    DRIVER = "Driver"
    INSPECTOR = "Inspector"
    DISPATCHER = "Dispatcher"


class ServiceZone(str, Enum):
    ZONE_NORTH = "ZONE_NORTH"
    ZONE_SOUTH = "ZONE_SOUTH"
    ZONE_EAST = "ZONE_EAST"
    ZONE_WEST = "ZONE_WEST"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AmnestyWindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class RouteDayStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class PickupRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class ItemCategory(str, Enum):
    STANDARD_FURNITURE = "STANDARD_FURNITURE"
    MATTRESS = "MATTRESS"
    APPLIANCE_NO_REFRIGERANT = "APPLIANCE_NO_REFRIGERANT"
    APPLIANCE_WITH_REFRIGERANT = "APPLIANCE_WITH_REFRIGERANT"
    ELECTRONICS = "ELECTRONICS"
    TIRES = "TIRES"
    PROHIBITED = "PROHIBITED"


class RefusalReasonCode(str, Enum):
    IMPROPER_PREPARATION = "IMPROPER_PREPARATION"
    PROHIBITED_ITEM = "PROHIBITED_ITEM"
    BLOCKED_ACCESS = "BLOCKED_ACCESS"
    UNSAFE_SETOUT = "UNSAFE_SETOUT"
    EXCEEDS_DECLARED_ITEMS = "EXCEEDS_DECLARED_ITEMS"


class MissedReasonCode(str, Enum):
    NO_SETOUT = "NO_SETOUT"
    NOT_VISIBLE = "NOT_VISIBLE"
    GATE_LOCKED = "GATE_LOCKED"


class SetoutClassification(str, Enum):
    AUTHORIZED_SETOUT = "AUTHORIZED_SETOUT"
    ILLEGAL_DUMPING = "ILLEGAL_DUMPING"


class DispositionRoute(str, Enum):
    LANDFILL = "LANDFILL"
    MATTRESS_RECYCLING = "MATTRESS_RECYCLING"
    REFRIGERANT_RECOVERY = "REFRIGERANT_RECOVERY"
    METAL_RECYCLING = "METAL_RECYCLING"
    E_WASTE = "E_WASTE"
    TIRE_RECYCLING = "TIRE_RECYCLING"


class FeeAssessmentKind(str, Enum):
    PROVISIONAL_QUOTE = "PROVISIONAL_QUOTE"
    FINAL_INVOICE = "FINAL_INVOICE"
    CONTAMINATION_PENALTY = "CONTAMINATION_PENALTY"
    ILLEGAL_DUMPING_FINE = "ILLEGAL_DUMPING_FINE"


class FeeAssessmentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class DumpingReportStatus(str, Enum):
    OPEN = "OPEN"
    DETERMINED_AUTHORIZED = "DETERMINED_AUTHORIZED"
    DETERMINED_ILLEGAL = "DETERMINED_ILLEGAL"
    DISMISSED = "DISMISSED"


class Determination(str, Enum):
    AUTHORIZED_SETOUT = "AUTHORIZED_SETOUT"
    ILLEGAL_DUMPING = "ILLEGAL_DUMPING"
    DISMISSED = "DISMISSED"


class NotificationKind(str, Enum):
    SCHEDULE_CONFIRMATION = "SCHEDULE_CONFIRMATION"
    REFUSAL_NOTICE = "REFUSAL_NOTICE"
    MISSED_NOTICE = "MISSED_NOTICE"
    CANCELLATION_NOTICE = "CANCELLATION_NOTICE"
    ILLEGAL_DUMPING_WARNING = "ILLEGAL_DUMPING_WARNING"


# common_fields: true — id + created_at + updated_at + version
class Household(TypedDict):
    id: str
    street_address: str
    service_zone: str
    status: str
    annual_allowance_items: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HouseholdAllowance(TypedDict):
    id: str
    household_id: str
    calendar_year: int
    items_consumed: int
    items_released: int
    over_allowance_items: int
    created_at: str
    updated_at: str
    version: int


class AmnestyWindow(TypedDict):
    id: str
    label: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteDay(TypedDict):
    id: str
    service_zone: str
    route_date: str
    max_load_units: int
    max_stops: int
    committed_load_units: int
    committed_stops: int
    projected_load_units: int
    projected_fullness_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupRequest(TypedDict):
    id: str
    household_id: str
    route_day_id: Optional[str]
    status: str
    scheduled_date: Optional[str]
    load_units: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    amnesty_applied: bool
    refusal_reason_code: Optional[str]
    missed_reason_code: Optional[str]
    setout_classification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickupItem(TypedDict):
    id: str
    pickup_request_id: str
    sequence_no: int
    category: str
    is_oversize: bool
    preparation_ack: bool
    item_fee_cents: int
    within_allowance: bool
    disposition_route: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    pickup_request_id: Optional[str]
    household_id: str
    kind: str
    amount_cents: int
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DumpingReport(TypedDict):
    id: str
    household_id: str
    pickup_request_id: Optional[str]
    reported_at: str
    status: str
    determination_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only emission record: ONLY id + created_at
class Notification(TypedDict):
    id: str
    pickup_request_id: str
    kind: str
    reason_code: Optional[str]
    message: str
    created_at: str
