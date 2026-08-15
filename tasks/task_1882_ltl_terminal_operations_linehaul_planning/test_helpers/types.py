"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class TerminalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class NmfcClass(str, Enum):
    CLASS_50 = "CLASS_50"
    CLASS_55 = "CLASS_55"
    CLASS_60 = "CLASS_60"
    CLASS_65 = "CLASS_65"
    CLASS_70 = "CLASS_70"
    CLASS_85 = "CLASS_85"
    CLASS_100 = "CLASS_100"
    CLASS_125 = "CLASS_125"


class AccessorialCode(str, Enum):
    LIFTGATE = "LIFTGATE"
    NOTIFY = "NOTIFY"
    RESIDENTIAL = "RESIDENTIAL"
    INSIDE = "INSIDE"


class ServiceStandard(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    GUARANTEED = "GUARANTEED"


class RatingStatus(str, Enum):
    UNRATED = "UNRATED"
    RATED = "RATED"
    INSPECTION_PENDING = "INSPECTION_PENDING"
    RERATED = "RERATED"
    BILLED = "BILLED"


class HandlingStatus(str, Enum):
    TENDERED = "TENDERED"
    ON_DOCK = "ON_DOCK"
    MANIFESTED = "MANIFESTED"
    IN_LINEHAUL = "IN_LINEHAUL"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    RECALLED = "RECALLED"


class StopStatus(str, Enum):
    PLANNED = "PLANNED"
    ARRIVED = "ARRIVED"
    PICKED_UP = "PICKED_UP"
    SKIPPED = "SKIPPED"


class DoorKind(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class DoorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DISPOSITIONED = "DISPOSITIONED"


class TrailerPosture(str, Enum):
    LOADING = "LOADING"
    READY = "READY"
    SEALED = "SEALED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    VOIDED = "VOIDED"


class ManifestEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class LegStatus(str, Enum):
    PLANNED = "PLANNED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class InspectionOutcome(str, Enum):
    PENDING = "PENDING"
    CONFIRMED_RECLASS = "CONFIRMED_RECLASS"
    REJECTED = "REJECTED"


class OsdCaseKind(str, Enum):
    OVERAGE = "OVERAGE"
    SHORTAGE = "SHORTAGE"
    DAMAGE = "DAMAGE"


class OsdCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


class UserRole(str, Enum):
    TERMINAL_ADMIN = "TerminalAdmin"
    DISPATCHER = "Dispatcher"
    DOCK_SUPERVISOR = "DockSupervisor"
    RATING_CLERK = "RatingClerk"
    OSD_CLERK = "OsdClerk"


# --- Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at, version) ---


class Terminal(TypedDict, total=False):
    id: str
    code: str
    name: str
    dock_doors: int
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    pro_number: str
    origin_terminal_id: str
    destination_terminal_id: str
    nmfc_class: str
    actual_weight_lbs: int
    length_in: int
    width_in: int
    height_in: int
    accessorial_codes: List[str]
    service_standard: str
    chargeable_weight_lbs: int
    dim_weight_lbs: int
    rated_amount_cents: int
    billed_amount_cents: int
    rating_status: str
    handling_status: str
    osd_hold: bool
    tendered_at_utc: str
    committed_delivery_utc: str
    delivered_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PickupRoute(TypedDict, total=False):
    id: str
    terminal_id: str
    route_date: str
    driver_id: str
    shift_start_minute: int
    shift_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupStop(TypedDict, total=False):
    id: str
    route_id: str
    shipment_id: str
    stop_sequence: int
    planned_arrival_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DockDoor(TypedDict, total=False):
    id: str
    terminal_id: str
    door_number: int
    door_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SortationBatch(TypedDict, total=False):
    id: str
    terminal_id: str
    inbound_door_id: str
    destination_terminal_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OutboundTrailer(TypedDict, total=False):
    id: str
    terminal_id: str
    destination_terminal_id: str
    outbound_door_id: str
    max_weight_lbs: int
    max_cube_cuft: int
    loaded_weight_lbs: int
    loaded_cube_cuft: int
    utilization_pct: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class ManifestEntry(TypedDict, total=False):
    id: str
    trailer_id: str
    shipment_id: str
    load_position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LinehaulLeg(TypedDict, total=False):
    id: str
    origin_terminal_id: str
    destination_terminal_id: str
    trailer_id: str
    planned_departure_utc: str
    planned_arrival_utc: str
    actual_departure_utc: Optional[str]
    actual_arrival_utc: Optional[str]
    provisional_eta_utc: str
    relay_sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only evidence (PRD §2.4): carries ONLY id + created_at among common fields.
class DimensionerScan(TypedDict, total=False):
    id: str
    shipment_id: str
    measured_length_in: int
    measured_width_in: int
    measured_height_in: int
    measured_weight_lbs: int
    scanned_by: str
    created_at: str


class Inspection(TypedDict, total=False):
    id: str
    shipment_id: str
    scan_id: str
    claimed_nmfc_class: str
    outcome: str
    adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


class OsdCase(TypedDict, total=False):
    id: str
    shipment_id: str
    case_kind: str
    claimed_amount_cents: int
    item_amounts_cents: List[int]
    awarded_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Point-in-time snapshot (PRD §2.4): carries ONLY id + created_at among common fields.
class ServiceStandardReport(TypedDict, total=False):
    id: str
    terminal_id: str
    report_date: str
    window_start_utc: str
    window_end_utc: str
    shipments_due: int
    shipments_on_time: int
    on_time_pct: float
    service_level_met: bool
    created_at: str
