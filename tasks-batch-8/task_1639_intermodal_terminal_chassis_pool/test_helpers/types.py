"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    TERMINAL_MANAGER = "TerminalManager"
    POOL_ADMINISTRATOR = "PoolAdministrator"
    YARD_PLANNER = "YardPlanner"
    RAIL_COORDINATOR = "RailCoordinator"
    GATE_SUPERVISOR = "GateSupervisor"
    GATE_CLERK = "GateClerk"
    MAINTENANCE_PLANNER = "MaintenancePlanner"
    BILLING_CLERK = "BillingClerk"


class TerminalPosture(str, Enum):
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    CLOSED = "CLOSED"


class ChassisStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT = "OUT"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class RoadabilityStatus(str, Enum):
    ROADABLE = "ROADABLE"
    UNROADABLE = "UNROADABLE"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ContainerStatus(str, Enum):
    INBOUND_TRAIN = "INBOUND_TRAIN"
    ON_GROUND = "ON_GROUND"
    MOUNTED = "MOUNTED"
    OUTBOUND_TRUCK = "OUTBOUND_TRUCK"
    DEPARTED = "DEPARTED"
    VOIDED = "VOIDED"


class IsoType(str, Enum):
    FT20 = "20FT"
    FT40 = "40FT"
    HC40 = "40HC"
    FT45 = "45FT"


class YardSlotStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    BLOCKED = "BLOCKED"
    RESERVED = "RESERVED"


class TrainStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    LOADING = "LOADING"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class AppointmentDirection(str, Enum):
    IN = "IN"
    OUT = "OUT"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class DamageKind(str, Enum):
    TIRE = "TIRE"
    BRAKE = "BRAKE"
    LIGHTS = "LIGHTS"
    FRAME = "FRAME"
    CONTAINER_DENT = "CONTAINER_DENT"
    CONTAINER_PUNCTURE = "CONTAINER_PUNCTURE"


class DamageSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SAFETY_CRITICAL = "SAFETY_CRITICAL"


class DamageStatus(str, Enum):
    OPEN = "OPEN"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
    REPAIRED = "REPAIRED"
    WAIVED = "WAIVED"


class LedgerEntryKind(str, Enum):
    PER_DIEM = "PER_DIEM"
    STORAGE = "STORAGE"
    FLIP_FEE = "FLIP_FEE"
    DAMAGE_REPAIR = "DAMAGE_REPAIR"


class LedgerEntryStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"
    WAIVED = "WAIVED"


# --- Entity TypedDicts (all primary resources carry id/created_at/updated_at/
# --- version per PRD §2.5) ---


class Terminal(TypedDict, total=False):
    id: str
    terminal_code: str
    rail_cutoff_minutes_before_departure: int
    gate_free_hours: int
    per_diem_rate_cents: int
    storage_rate_cents: int
    flip_fee_cents: int
    max_stack_height: int
    yard_slot_count: int
    yard_slots_in_use: int
    yard_slots_free: int
    posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class ChassisPool(TypedDict, total=False):
    id: str
    terminal_id: str
    pool_code: str
    total_chassis_count: int
    available_chassis_count: int
    reserved_chassis_count: int
    out_chassis_count: int
    maintenance_chassis_count: int
    flip_fee_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Chassis(TypedDict, total=False):
    id: str
    pool_id: str
    chassis_number: str
    status: str
    roadability_status: str
    last_inspection_at: Optional[str]
    out_gate_transaction_id: Optional[str]
    current_container_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChassisMembership(TypedDict, total=False):
    id: str
    pool_id: str
    carrier_id: str
    membership_status: str
    flip_fee_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    scac_code: str
    carrier_name: str
    billing_credit_limit_cents: int
    outstanding_billing_cents: int
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    terminal_id: str
    container_number: str
    iso_type: str
    status: str
    free_time_expires_at: Optional[str]
    in_ground_at: Optional[str]
    yard_slot_id: Optional[str]
    stack_height: Optional[int]
    planned_train_id: str
    out_gate_transaction_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class YardSlot(TypedDict, total=False):
    id: str
    terminal_id: str
    slot_code: str
    row: str
    tier_max: int
    status: str
    occupied_container_id: Optional[str]
    current_height: int
    created_at: str
    updated_at: str
    version: int


class Train(TypedDict, total=False):
    id: str
    terminal_id: str
    train_symbol: str
    scheduled_departure_utc: str
    actual_departure_utc: Optional[str]
    status: str
    rail_cutoff_at: str
    created_at: str
    updated_at: str
    version: int


class GateAppointment(TypedDict, total=False):
    id: str
    terminal_id: str
    carrier_id: str
    container_id: str
    direction: str
    window_start_utc: str
    window_end_utc: str
    status: str
    assigned_driver_id: Optional[str]
    checked_in_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GateTransaction(TypedDict, total=False):
    id: str
    terminal_id: str
    appointment_id: str
    container_id: str
    chassis_id: Optional[str]
    carrier_id: str
    direction: str
    driver_id: str
    gate_lane: str
    processed_at: Optional[str]
    driver_turn_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageInspection(TypedDict, total=False):
    id: str
    terminal_id: str
    gate_transaction_id: str
    chassis_id: Optional[str]
    container_id: Optional[str]
    damage_kind: str
    severity: str
    repair_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingLedgerEntry(TypedDict, total=False):
    id: str
    terminal_id: str
    container_id: Optional[str]
    chassis_id: Optional[str]
    carrier_id: str
    entry_kind: str
    amount_cents: int
    applied_cents: int
    status: str
    period_start_utc: Optional[str]
    period_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int
