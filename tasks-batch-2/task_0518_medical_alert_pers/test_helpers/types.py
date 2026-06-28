"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the PRD's entity definitions and state machines. Envelope types are
provided by the framework and are not redefined here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUBSCRIBER = "Subscriber"
    CALL_CENTER_AGENT = "CallCenterAgent"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class SubscriberStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ContractServiceStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLED = "CANCELLED"


class ContractBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    WRITTEN_OFF = "WRITTEN_OFF"


class DeviceType(str, Enum):
    PENDANT = "PENDANT"
    WRISTBAND = "WRISTBAND"
    MOBILE_GPS = "MOBILE_GPS"
    HOME_BASE = "HOME_BASE"


class DeviceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    NEEDS_TEST = "NEEDS_TEST"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class BatteryHealth(str, Enum):
    GOOD = "GOOD"
    LOW = "LOW"
    CRITICAL = "CRITICAL"


class ContactRelationship(str, Enum):
    CAREGIVER = "CAREGIVER"
    FAMILY = "FAMILY"
    NEIGHBOR = "NEIGHBOR"
    PHYSICIAN = "PHYSICIAN"


class SignalType(str, Enum):
    MANUAL_BUTTON = "MANUAL_BUTTON"
    FALL_DETECTED = "FALL_DETECTED"
    BATTERY_CRITICAL = "BATTERY_CRITICAL"
    PERIODIC_CHECKIN_MISSED = "PERIODIC_CHECKIN_MISSED"


class AlarmPriority(str, Enum):
    ROUTINE = "ROUTINE"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class AlarmStatus(str, Enum):
    SIGNAL_RECEIVED = "SIGNAL_RECEIVED"
    AGENT_ASSIGNED = "AGENT_ASSIGNED"
    CONTACTING_SUBSCRIBER = "CONTACTING_SUBSCRIBER"
    ESCALATING = "ESCALATING"
    DISPATCHED_911 = "DISPATCHED_911"
    RESOLVED_OK = "RESOLVED_OK"
    FALSE_ALARM = "FALSE_ALARM"


class DispatchActionType(str, Enum):
    CALL_SUBSCRIBER = "CALL_SUBSCRIBER"
    CALL_CONTACT = "CALL_CONTACT"
    DISPATCH_911 = "DISPATCH_911"
    MARK_FALSE_ALARM = "MARK_FALSE_ALARM"
    RESOLVE_OK = "RESOLVE_OK"


class DispatchOutcome(str, Enum):
    ANSWERED = "ANSWERED"
    NO_ANSWER = "NO_ANSWER"
    DISPATCHED = "DISPATCHED"
    CONFIRMED_OK = "CONFIRMED_OK"
    CONFIRMED_FALSE = "CONFIRMED_FALSE"


class DeviceTestResult(str, Enum):
    PASS = "PASS"
    FAIL_SIGNAL = "FAIL_SIGNAL"
    FAIL_BATTERY = "FAIL_BATTERY"


class EquipmentReturnStatus(str, Enum):
    INITIATED = "INITIATED"
    KIT_SENT = "KIT_SENT"
    RECEIVED = "RECEIVED"
    INSPECTED_OK = "INSPECTED_OK"
    DAMAGED = "DAMAGED"
    CLOSED = "CLOSED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    UNRETURNED = "UNRETURNED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class HoldStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true -> id + created_at + updated_at + version
# common_fields: false (DeviceTest) -> id + created_at only
# ---------------------------------------------------------------------------
class MonitoringPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    fall_detection_addon_cents: int
    included_test_interval_days: int
    response_sla_seconds: int
    early_termination_fee_cents: int
    min_commitment_months: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    full_name: str
    email: str
    residence_address: str
    phone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    subscriber_id: str
    plan_id: str
    pinned_monthly_fee_cents: int
    pinned_addon_cents: int
    pinned_etf_cents: int
    pinned_min_commitment_months: int
    billing_status: str
    service_status: str
    activated_at: Optional[str]
    paid_through_at: Optional[str]
    cancellation_effective_at: Optional[str]
    refund_cents: int
    etf_charged_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    contract_id: str
    serial_number: str
    device_type: str
    fall_detection_enabled: bool
    status: str
    battery_pct: int
    battery_health: str
    last_test_at: Optional[str]
    next_test_due_at: Optional[str]
    open_alarm_count: int
    created_at: str
    updated_at: str
    version: int


class EmergencyContact(TypedDict):
    id: str
    subscriber_id: str
    name: str
    phone: str
    relationship: str
    priority_rank: int
    escalates_to_contact_id: Optional[str]
    can_authorize_911: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class AlarmEvent(TypedDict):
    id: str
    device_id: str
    assigned_agent_id: Optional[str]
    signal_type: str
    priority: str
    status: str
    signal_received_at: Optional[str]
    agent_assigned_at: Optional[str]
    resolved_at: Optional[str]
    sla_breached: bool
    current_escalation_rank: int
    dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class DispatchAction(TypedDict):
    id: str
    alarm_event_id: str
    action_type: str
    target_contact_id: Optional[str]
    outcome: str
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# DeviceTest is append-only (common_fields: false): id + created_at only.
class DeviceTest(TypedDict):
    id: str
    device_id: str
    reported_battery_pct: int
    signal_ok: bool
    result: str
    tested_at: Optional[str]
    created_at: str


class EquipmentReturn(TypedDict):
    id: str
    contract_id: str
    device_id: str
    status: str
    condition_grade: Optional[str]
    damage_fee_cents: int
    due_back_at: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgentShift(TypedDict):
    id: str
    agent_user_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringHold(TypedDict):
    id: str
    device_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
