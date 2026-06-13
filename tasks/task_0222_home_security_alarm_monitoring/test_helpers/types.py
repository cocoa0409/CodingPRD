"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Entities carrying the common
mutable fields (id, created_at, updated_at, version) are distinguished from
the immutable MonitoringPlan price-book row, which carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status / enum value sets ─────────────────────────────────────────

class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLED = "CANCELLED"


class MonitoringStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ArmingState(str, Enum):
    DISARMED = "DISARMED"
    ARMED_STAY = "ARMED_STAY"
    ARMED_AWAY = "ARMED_AWAY"


class CommunicatorHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class PrimaryPath(str, Enum):
    BROADBAND = "BROADBAND"
    CELLULAR = "CELLULAR"


class PremisesType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PRO = "PRO"


class SensorStatus(str, Enum):
    ENROLLED = "ENROLLED"
    BYPASSED = "BYPASSED"
    REMOVED = "REMOVED"


class SensorType(str, Enum):
    DOOR = "DOOR"
    MOTION = "MOTION"
    GLASS_BREAK = "GLASS_BREAK"
    SMOKE = "SMOKE"
    CO = "CO"
    PANIC = "PANIC"


class AlarmEventStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    DISPATCHED = "DISPATCHED"
    RESOLVED_REAL = "RESOLVED_REAL"
    RESOLVED_FALSE = "RESOLVED_FALSE"
    SUPPRESSED = "SUPPRESSED"


class SignalType(str, Enum):
    BURGLARY = "BURGLARY"
    FIRE = "FIRE"
    MEDICAL = "MEDICAL"
    PANIC = "PANIC"


class RoutedService(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    MEDICAL = "MEDICAL"


class Resolution(str, Enum):
    REAL = "REAL"
    FALSE_ALARM = "FALSE_ALARM"


class DispatchStatus(str, Enum):
    ORDERED = "ORDERED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SettlementStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class UserRole(str, Enum):
    SUBSCRIBER = "Subscriber"
    MONITORING_OPERATOR = "MonitoringOperator"
    ADMINISTRATOR = "Administrator"


# ─── Entity TypedDicts ────────────────────────────────────────────────

# MonitoringPlan: immutable price-book row — ONLY id + created_at as system
# fields. No updated_at, no version.
class MonitoringPlan(TypedDict):
    id: str
    created_at: str
    tier: str
    monthly_fee_cents: int
    police_dispatch_included: bool
    max_sensors: int
    cellular_backup_included: bool


class Account(TypedDict):
    id: str
    premises_type: str
    plan_id: str
    contract_status: str
    monitoring_status: str
    contract_start_utc: Optional[str]
    contract_term_months: int
    cycle_anchor_utc: Optional[str]
    current_tier: Optional[str]
    monitoring_balance_cents: int
    false_alarm_count_cycle: int
    early_termination_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class SecuritySystem(TypedDict):
    id: str
    account_id: str
    arming_state: str
    test_mode: bool
    test_mode_expires_utc: Optional[str]
    primary_path: str
    cellular_signal_dbm: int
    backup_battery_pct: int
    last_checkin_minutes_ago: int
    communicator_health: str
    sensor_count: int
    created_at: str
    updated_at: str
    version: int


class Sensor(TypedDict):
    id: str
    system_id: str
    zone_number: int
    sensor_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AlarmEvent(TypedDict):
    id: str
    system_id: str
    sensor_id: str
    signal_type: str
    status: str
    routed_service: Optional[str]
    raised_utc: str
    resolution: Optional[str]
    chargeable_ordinal: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    alarm_event_id: str
    account_id: str
    service: str
    status: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    account_id: str
    permit_number: str
    status: str
    filed_days_late: int
    cycle_anchor_utc: str
    fee_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict):
    id: str
    account_id: str
    alarm_event_id: str
    amount_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int
