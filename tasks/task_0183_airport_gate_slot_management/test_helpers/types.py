"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum --------------------------------------------------------------
class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    GATE_CONTROLLER = "GateController"
    RAMP_AGENT = "RampAgent"
    SLOT_COORDINATOR = "SlotCoordinator"


# --- Status enums -----------------------------------------------------------
class GateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RemoteStandStatus(str, Enum):
    ACTIVE = "ACTIVE"


class CuteUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class GroundEquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class EquipmentType(str, Enum):
    GPU = "GPU"
    PUSHBACK_TUG = "PUSHBACK_TUG"
    BELT_LOADER = "BELT_LOADER"
    AIR_START = "AIR_START"


class FlightScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DIVERTED = "DIVERTED"


class FlightHandlingStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    AT_GATE = "AT_GATE"
    TOWED_OFF = "TOWED_OFF"
    DEPARTED = "DEPARTED"


class SlotPermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    USED = "USED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class MovementType(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"


class GateAssignmentStatus(str, Enum):
    PLANNED = "PLANNED"
    OCCUPIED = "OCCUPIED"
    TOWED_AWAY = "TOWED_AWAY"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class StandType(str, Enum):
    GATE = "GATE"
    REMOTE = "REMOTE"


class AllocationStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Gate(TypedDict):
    id: str
    code: str
    terminal: str
    max_wingspan_m: float
    is_cute_equipped: bool
    buffer_minutes: int
    status: str
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class RemoteStand(TypedDict):
    id: str
    code: str
    max_wingspan_m: float
    capacity: int
    status: str
    occupancy_count: int
    created_at: str
    updated_at: str
    version: int


class CuteUnit(TypedDict):
    id: str
    label: str
    terminal: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GroundEquipment(TypedDict):
    id: str
    asset_tag: str
    equipment_type: str
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict):
    id: str
    flight_no: str
    aircraft_wingspan_m: float
    sched_arrival_utc: Optional[str]
    sched_departure_utc: str
    min_turn_minutes: int
    schedule_status: str
    handling_status: str
    scheduled_turn_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SlotPermit(TypedDict):
    id: str
    flight_id: str
    movement_type: str
    slot_time_utc: str
    tolerance_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GateAssignment(TypedDict):
    id: str
    flight_id: str
    stand_type: str
    gate_id: Optional[str]
    remote_stand_id: Optional[str]
    start_utc: str
    end_utc: str
    status: str
    tow_target_stand_id: Optional[str]
    occupancy_minutes: int
    created_at: str
    updated_at: str
    version: int


class CuteAllocation(TypedDict):
    id: str
    flight_id: str
    cute_unit_id: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GseAllocation(TypedDict):
    id: str
    flight_id: str
    equipment_id: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — ClockState carries only its single timestamp field.
class ClockState(TypedDict):
    current_utc: str
