"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_OPERATOR = "ProgramOperator"
    AGGREGATOR = "Aggregator"
    CUSTOMER = "Customer"
    AUDITOR = "Auditor"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AggregatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DeviceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class DeviceType(str, Enum):
    BATTERY = "BATTERY"
    THERMOSTAT = "THERMOSTAT"
    EV_CHARGER = "EV_CHARGER"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    OPTED_OUT = "OPTED_OUT"
    TERMINATED = "TERMINATED"


class DispatchEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTIFIED = "NOTIFIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class DispatchStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CURTAILING = "CURTAILING"
    OVERRIDDEN = "OVERRIDDEN"
    OPTED_OUT = "OPTED_OUT"
    COMPLETED = "COMPLETED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    REVISED = "REVISED"


class PaymentStatus(str, Enum):
    ISSUED = "ISSUED"
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"


class BaselineMethod(str, Enum):
    TEN_OF_TEN = "TEN_OF_TEN"
    WEATHER_REGRESSION = "WEATHER_REGRESSION"


class SettlementMethod(str, Enum):
    PAY_FOR_PERFORMANCE = "PAY_FOR_PERFORMANCE"
    CAPACITY_PAYMENT = "CAPACITY_PAYMENT"


class ReadingType(str, Enum):
    BASELINE_WINDOW = "BASELINE_WINDOW"
    EVENT_WINDOW = "EVENT_WINDOW"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Program(TypedDict):
    id: str
    name: str
    utility_name: str
    incentive_rate_cents_per_kwh: int
    penalty_rate_cents_per_kwh: int
    capacity_incentive_cents_per_kw: int
    baseline_method: str
    settlement_method: str
    performance_floor_pct: float
    notification_lead_minutes: int
    max_events_per_season: int
    season_start_date: str
    season_end_date: str
    status: str
    total_committed_kw: float
    created_at: str
    updated_at: str
    version: int


class Aggregator(TypedDict):
    id: str
    name: str
    contact_email: str
    status: str
    enrolled_committed_kw: float
    season_delivered_kwh: float
    paid_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    email: str
    service_address: str
    utility_account_id: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    customer_id: str
    aggregator_id: str
    device_type: str
    nameplate_kw: float
    capacity_kwh: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    device_id: str
    program_id: str
    committed_kw: float
    status: str
    season_delivered_kwh: float
    created_at: str
    updated_at: str
    version: int


class DispatchEvent(TypedDict):
    id: str
    program_id: str
    window_start: str
    window_end: str
    target_reduction_kw: float
    baseline_method_snapshot: str
    dispatched_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    dispatch_event_id: str
    enrollment_id: str
    assigned_reduction_kw: float
    baseline_kw: Optional[float]
    avg_event_load_kw: Optional[float]
    actual_reduction_kw: Optional[float]
    delivered_kwh: Optional[float]
    performance_ratio: Optional[float]
    net_payment_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    dispatch_event_id: str
    method_snapshot: str
    total_delivered_kwh: float
    net_payment_cents: int
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    settlement_id: str
    aggregator_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class MeterReading(TypedDict):
    id: str
    device_id: str
    dispatch_event_id: Optional[str]
    interval_start: str
    interval_end: str
    kw_load: float
    reading_type: str
    created_at: str
