"""Domain types for the Smart Irrigation API.

Status enums and entity TypedDicts derived from PRD §2.4 (Common Resource
Properties) and §3 entity prose.

PRD §2.4 distinguishes two field-shape classes:
- Standard resources (Tenant, Plot, Sensor, IrrigationPlan, ValveGroup,
  ControlCommand, WaterQuota, Alert, WaterBill) carry id, created_at,
  updated_at, version.
- Append-only entries (SensorReading, AuditLog) carry only id and
  created_at — tests MUST NOT assert updated_at or version on these.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    WATER_ADMIN = "WaterAdmin"
    OPERATOR = "Operator"
    DEVICE_AGENT = "DeviceAgent"
    TENANT = "Tenant"


# ---------------------------------------------------------------------------
# Status / lifecycle enums
# ---------------------------------------------------------------------------
class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PlotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FALLOW = "FALLOW"


class CropType(str, Enum):
    WHEAT = "WHEAT"
    CORN = "CORN"
    RICE = "RICE"
    COTTON = "COTTON"
    VEGETABLE = "VEGETABLE"


class CropStage(str, Enum):
    SEEDLING = "SEEDLING"
    VEGETATIVE = "VEGETATIVE"
    FLOWERING = "FLOWERING"
    FRUITING = "FRUITING"
    MATURE = "MATURE"


class SensorType(str, Enum):
    SOIL_MOISTURE = "SOIL_MOISTURE"
    SOIL_TEMPERATURE = "SOIL_TEMPERATURE"
    SOIL_EC = "SOIL_EC"
    WEATHER_STATION = "WEATHER_STATION"


class SensorStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    FAULTY = "FAULTY"


class ReadingValidity(str, Enum):
    VALID = "VALID"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    ABNORMAL_FILTERED = "ABNORMAL_FILTERED"
    ARCHIVED = "ARCHIVED"


class IrrigationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IrrigationPlanSource(str, Enum):
    AUTO = "AUTO"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class ControlMode(str, Enum):
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL = "PARALLEL"


class ControlCommandStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHING = "DISPATCHING"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    OFFLINE_LOCAL = "OFFLINE_LOCAL"


class DispatchMode(str, Enum):
    REMOTE = "REMOTE"
    LOCAL_DEGRADED = "LOCAL_DEGRADED"


class FeedbackPhase(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class QuotaUsageState(str, Enum):
    UNDER = "UNDER"
    WARNING = "WARNING"
    OVER = "OVER"


class QuotaApprovalState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AlertSubjectType(str, Enum):
    SENSOR = "SENSOR"
    PLOT = "PLOT"
    VALVE_GROUP = "VALVE_GROUP"


class AlertRuleCode(str, Enum):
    SENSOR_OFFLINE = "SENSOR_OFFLINE"
    ABNORMAL_FLOW = "ABNORMAL_FLOW"
    PIPE_BURST_SUSPICION = "PIPE_BURST_SUSPICION"
    VALVE_FAULT = "VALVE_FAULT"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class WaterBillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class DisputeOutcome(str, Enum):
    REJECT = "REJECT"
    ACCEPT = "ACCEPT"


class AuditActionType(str, Enum):
    CONTROL_COMMAND_ISSUED = "CONTROL_COMMAND_ISSUED"
    CONTROL_COMMAND_FAILED = "CONTROL_COMMAND_FAILED"
    QUOTA_ALLOCATED = "QUOTA_ALLOCATED"
    QUOTA_OVERRIDE_APPROVED = "QUOTA_OVERRIDE_APPROVED"
    QUOTA_OVERRIDE_REJECTED = "QUOTA_OVERRIDE_REJECTED"
    PLAN_OVERRIDDEN = "PLAN_OVERRIDDEN"


class AuditSubjectTypeEnum(str, Enum):
    CONTROL_COMMAND = "CONTROL_COMMAND"
    WATER_QUOTA = "WATER_QUOTA"
    IRRIGATION_PLAN = "IRRIGATION_PLAN"


class EventType(str, Enum):
    WEATHER_RAINFALL = "WEATHER_RAINFALL"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"


# ---------------------------------------------------------------------------
# Standard (versioned) entity TypedDicts (PRD §2.4)
# ---------------------------------------------------------------------------
class Tenant(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Plot(TypedDict, total=False):
    id: str
    tenant_id: str
    name: str
    area_hectares: float
    crop_type: str
    crop_stage: str
    pump_id: str
    status: str
    last_irrigated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sensor(TypedDict, total=False):
    id: str
    plot_id: str
    sensor_type: str
    poll_interval_seconds: int
    min_valid_value: float
    max_valid_value: float
    status: str
    last_reading_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IrrigationPlan(TypedDict, total=False):
    id: str
    plot_id: str
    window_start: str
    window_end: str
    planned_volume_liters: float
    source: str
    status: str
    plan_version: int
    parent_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValveGroup(TypedDict, total=False):
    id: str
    tenant_id: str
    name: str
    pump_id: str
    valve_ids: List[str]
    control_mode: str
    max_parallel_valves: int
    created_at: str
    updated_at: str
    version: int


class ControlCommand(TypedDict, total=False):
    id: str
    plan_id: str
    valve_group_id: str
    requested_volume_liters: float
    dispatch_mode: str
    status: str
    actual_volume_liters: float
    feedback_received_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaterQuota(TypedDict, total=False):
    id: str
    plot_id: str
    period_start: str
    period_end: str
    allocated_liters: float
    carry_forward_liters: float
    provisional_used_liters: float
    final_used_liters: float
    warning_threshold_pct: float
    usage_state: str
    approval_state: str
    approval_extra_liters: float
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    tenant_id: str
    subject_type: str
    subject_id: str
    rule_code: str
    severity: str
    status: str
    acknowledged_by: Optional[str]
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaterBill(TypedDict, total=False):
    id: str
    tenant_id: str
    plot_id: str
    period_start: str
    period_end: str
    peak_liters: float
    offpeak_liters: float
    line_items: List[Dict[str, Any]]
    total_amount_cents: int
    amount_paid_cents: int
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entity TypedDicts (no updated_at / no version per PRD §2.4)
# ---------------------------------------------------------------------------
class SensorReading(TypedDict, total=False):
    id: str
    sensor_id: str
    value: float
    reading_timestamp: str
    validity: str
    archived: bool
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action_type: str
    subject_type: str
    subject_id: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "TenantStatus",
    "PlotStatus",
    "CropType",
    "CropStage",
    "SensorType",
    "SensorStatus",
    "ReadingValidity",
    "IrrigationPlanStatus",
    "IrrigationPlanSource",
    "ControlMode",
    "ControlCommandStatus",
    "DispatchMode",
    "FeedbackPhase",
    "QuotaUsageState",
    "QuotaApprovalState",
    "AlertSubjectType",
    "AlertRuleCode",
    "AlertSeverity",
    "AlertStatus",
    "WaterBillStatus",
    "DisputeOutcome",
    "AuditActionType",
    "AuditSubjectTypeEnum",
    "EventType",
    "Tenant",
    "Plot",
    "Sensor",
    "IrrigationPlan",
    "ValveGroup",
    "ControlCommand",
    "WaterQuota",
    "Alert",
    "WaterBill",
    "SensorReading",
    "AuditLog",
]
