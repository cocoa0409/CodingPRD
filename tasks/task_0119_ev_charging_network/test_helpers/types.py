"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the EV Charging Network PRD §3 and the
field/status vocabulary it defines. Enums use the exact string spellings from
the PRD prose.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    CPO_OPERATOR = "CPOOperator"
    DRIVER = "Driver"
    STATION_CONTROLLER = "StationController"


# --- Enums (PRD §3) ---
class ConnectorType(str, Enum):
    CCS = "CCS"
    CHADEMO = "CHADEMO"
    J1772 = "J1772"
    NACS = "NACS"


class AllocationPolicy(str, Enum):
    PROPORTIONAL = "PROPORTIONAL"
    PRIORITY = "PRIORITY"


class PricingMode(str, Enum):
    ENERGY_BASED = "ENERGY_BASED"
    TIME_BASED = "TIME_BASED"


class OcppStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    FAULTED = "FAULTED"
    UNAVAILABLE = "UNAVAILABLE"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CONSUMED = "CONSUMED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ChargingStatus(str, Enum):
    PREPARING = "PREPARING"
    CHARGING = "CHARGING"
    SUSPENDED = "SUSPENDED"
    FINISHING = "FINISHING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    RATED = "RATED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ReadingContext(str, Enum):
    TRANSACTION_BEGIN = "TRANSACTION_BEGIN"
    SAMPLE_PERIODIC = "SAMPLE_PERIODIC"
    TRANSACTION_END = "TRANSACTION_END"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class LineItemStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class TriggerReason(str, Enum):
    SESSION_START = "SESSION_START"
    SESSION_STOP = "SESSION_STOP"
    SESSION_SUSPEND = "SESSION_SUSPEND"
    MANUAL_REBALANCE = "MANUAL_REBALANCE"


# --- Entities carrying common fields (id, created_at, updated_at, version) ---
class Site(TypedDict):
    id: str
    name: str
    circuit_limit_kw: float
    allocation_policy: str
    demand_charge_threshold_kw: float
    demand_avoidance_armed: bool
    allocated_total_kw: float
    active_session_count: int
    created_at: str
    updated_at: str
    version: int


class Stall(TypedDict):
    id: str
    site_id: str
    connector_type: str
    max_power_kw: float
    ocpp_status: str
    reservation_priority: int
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    email: str
    full_name: str
    home_emsp_id: str
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EMSP(TypedDict):
    id: str
    name: str
    commission_pct: float
    receivable_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Tariff(TypedDict):
    id: str
    site_id: str
    connector_type: str
    pricing_mode: str
    session_fee_cents: int
    energy_tier_1_max_kwh: float
    energy_tier_2_max_kwh: float
    energy_rate_t1_cents: int
    energy_rate_t2_cents: int
    energy_rate_t3_cents: int
    time_rate_cents_per_min: int
    idle_grace_minutes: int
    idle_fee_cents_per_min: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    stall_id: str
    driver_id: str
    window_start: str
    window_end: str
    status: str
    hold_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ChargingSession(TypedDict):
    id: str
    stall_id: str
    driver_id: str
    tariff_id: Optional[str]
    reservation_id: Optional[str]
    emsp_id: Optional[str]
    is_roaming: bool
    charging_status: str
    billing_status: str
    energy_delivered_kwh: float
    charging_minutes: int
    idle_minutes: int
    allocated_power_kw: float
    total_cost_cents: int
    idle_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    emsp_id: str
    status: str
    line_item_count: int
    total_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class SettlementLineItem(TypedDict):
    id: str
    batch_id: str
    session_id: str
    gross_amount_cents: int
    commission_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadAllocation(TypedDict):
    id: str
    site_id: str
    trigger_reason: str
    policy_used: str
    cap_kw: float
    allocated_total_kw: float
    session_count: int
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity (common_fields false): only id + created_at (PRD §2.4) ---
class MeterEvent(TypedDict):
    id: str
    session_id: str
    meter_kwh: float
    sampled_at: str
    reading_context: str
    created_at: str
    # No updated_at, no version — MeterEvent is immutable after creation.
