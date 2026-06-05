"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are taken from the Container Terminal & Port
Operations PRD. Two resource types are append-only audit records that carry
ONLY id + created_at (no updated_at, no version): the reefer reading and the
equipment interchange receipt.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    TERMINAL_ADMIN = "TerminalAdmin"
    BERTH_PLANNER = "BerthPlanner"
    YARD_PLANNER = "YardPlanner"
    GATE_OPERATOR = "GateOperator"
    CUSTOMS_OFFICER = "CustomsOfficer"
    REEFER_TECHNICIAN = "ReeferTechnician"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class BerthStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CLOSED = "CLOSED"


class BerthWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BERTHED = "BERTHED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class CustomsStatus(str, Enum):
    PENDING = "PENDING"
    HELD = "HELD"
    CLEARED = "CLEARED"


class HandlingStatus(str, Enum):
    ON_VESSEL = "ON_VESSEL"
    GROUNDED = "GROUNDED"
    GATED_OUT = "GATED_OUT"


class YardSlotStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"


class GateAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    ARRIVED = "ARRIVED"
    FULFILLED = "FULFILLED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CustomsHoldReason(str, Enum):
    INSPECTION = "INSPECTION"
    DOCUMENTATION = "DOCUMENTATION"
    DUTY_UNPAID = "DUTY_UNPAID"


class CustomsHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class EirDirection(str, Enum):
    GATE_IN = "GATE_IN"
    GATE_OUT = "GATE_OUT"


class EirCondition(str, Enum):
    SOUND = "SOUND"
    DAMAGED = "DAMAGED"


class DemurrageInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    WAIVED = "WAIVED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts — full-lifecycle entities carry id/created_at/updated_at/version
# --------------------------------------------------------------------------- #
class Berth(TypedDict):
    id: str
    code: str
    length_m: int
    draft_m: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    imo_number: str
    name: str
    loa_m: int
    draft_m: float
    free_time_days: int
    created_at: str
    updated_at: str
    version: int


class BerthWindow(TypedDict):
    id: str
    berth_id: str
    vessel_id: str
    eta: str
    etd: str
    actual_berth_at: Optional[str]
    actual_depart_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict):
    id: str
    container_number: str
    vessel_id: str
    berth_window_id: str
    is_reefer: bool
    setpoint_c: Optional[float]
    yard_slot_id: Optional[str]
    customs_status: str
    handling_status: str
    free_time_expires_at: Optional[str]
    demurrage_due_cents: int
    created_at: str
    updated_at: str
    version: int


class YardSlot(TypedDict):
    id: str
    block: str
    bay: int
    row: int
    tier: int
    is_reefer_rack: bool
    below_slot_id: Optional[str]
    occupied_by_container_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GateAppointment(TypedDict):
    id: str
    container_id: str
    truck_plate: str
    window_start: str
    window_end: str
    status: str
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class CustomsHold(TypedDict):
    id: str
    container_id: str
    reason: str
    placed_at: str
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DemurrageInvoice(TypedDict):
    id: str
    container_id: str
    chargeable_days: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only audit records — carry ONLY id + created_at (no updated_at/version)
# --------------------------------------------------------------------------- #
class ReeferReading(TypedDict):
    id: str
    container_id: str
    recorded_at: str
    temperature_c: float
    is_excursion: bool
    created_at: str


class EquipmentInterchangeReceipt(TypedDict):
    id: str
    container_id: str
    gate_appointment_id: Optional[str]
    direction: str
    condition: str
    damage_note: Optional[str]
    recorded_at: str
    created_at: str
