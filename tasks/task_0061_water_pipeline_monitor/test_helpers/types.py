"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4 each entity has one of
two shapes:

- Versioned (id + created_at + updated_at + version):
  Network, TopologyVersion, DMA, Device, Alert, LeakInvestigation,
  WorkOrder.

- Append-only (id + created_at ONLY; NO updated_at, NO version):
  PipelineNode, PipelineSegment, Reading, WaterBalanceReport, SyncEvent,
  AuditLog. WaterBalanceReport additionally carries published_at and is
  immutable thereafter.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TOPOLOGY_ENGINEER = "TopologyEngineer"
    TOPOLOGY_APPROVER = "TopologyApprover"
    CONTROL_OPERATOR = "ControlOperator"
    MAINTENANCE_SUPERVISOR = "MaintenanceSupervisor"
    TECHNICIAN = "Technician"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class TopologyVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class DMAStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class DeviceStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"
    DECOMMISSIONED = "DECOMMISSIONED"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertKind(str, Enum):
    PRESSURE_HIGH = "PRESSURE_HIGH"
    PRESSURE_LOW = "PRESSURE_LOW"
    FLOW_SPIKE = "FLOW_SPIKE"
    FLOW_NIGHT_HIGH = "FLOW_NIGHT_HIGH"
    CROSS_SENSOR_DISAGREEMENT = "CROSS_SENSOR_DISAGREEMENT"


class LeakInvestigationStatus(str, Enum):
    OPEN = "OPEN"
    NARROWED = "NARROWED"
    DISPATCHED = "DISPATCHED"
    CONFIRMED_LEAK = "CONFIRMED_LEAK"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class WorkOrderStatus(str, Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    PARTS_PENDING = "PARTS_PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    CLOSED_REJECTED = "CLOSED_REJECTED"
    CANCELLED = "CANCELLED"


class WorkOrderPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class WorkOrderOrigin(str, Enum):
    ALERT_AUTO = "ALERT_AUTO"
    INVESTIGATION = "INVESTIGATION"
    INSPECTION_FINDING = "INSPECTION_FINDING"


class NodeKind(str, Enum):
    JUNCTION = "JUNCTION"
    VALVE = "VALVE"
    PUMP_STATION = "PUMP_STATION"
    RESERVOIR = "RESERVOIR"
    CUSTOMER_TAP = "CUSTOMER_TAP"


class SegmentMaterial(str, Enum):
    PVC = "PVC"
    DUCTILE_IRON = "DUCTILE_IRON"
    STEEL = "STEEL"
    HDPE = "HDPE"


class DeviceProtocol(str, Enum):
    NB_IOT = "NB_IOT"
    LORA = "LORA"
    WIRED = "WIRED"


class SensorKind(str, Enum):
    PRESSURE = "PRESSURE"
    FLOW = "FLOW"
    METER = "METER"


class ReadingValidity(str, Enum):
    ACCEPTED = "ACCEPTED"
    ABNORMAL_OUT_OF_RANGE = "ABNORMAL_OUT_OF_RANGE"
    ABNORMAL_STALE = "ABNORMAL_STALE"
    ABNORMAL_DUPLICATE = "ABNORMAL_DUPLICATE"


class ArchiveTier(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


class LeakClass(str, Enum):
    LEAK_CONFIRMED = "LEAK_CONFIRMED"
    JOINT_FAILURE = "JOINT_FAILURE"
    PIPE_BURST = "PIPE_BURST"
    NO_LEAK_FOUND = "NO_LEAK_FOUND"


class AuditAction(str, Enum):
    TOPOLOGY_SUBMITTED = "TOPOLOGY_SUBMITTED"
    TOPOLOGY_PUBLISHED = "TOPOLOGY_PUBLISHED"
    TOPOLOGY_REJECTED = "TOPOLOGY_REJECTED"
    TOPOLOGY_ROLLED_BACK = "TOPOLOGY_ROLLED_BACK"
    ALERT_ACK = "ALERT_ACK"
    ALERT_SUPPRESSED = "ALERT_SUPPRESSED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    DMA_POSTURE_CHANGED = "DMA_POSTURE_CHANGED"
    WORK_ORDER_VERIFIED = "WORK_ORDER_VERIFIED"


class SyncEventType(str, Enum):
    TOPOLOGY_PUBLISHED = "TOPOLOGY_PUBLISHED"
    ALERT_OPENED = "ALERT_OPENED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    WORK_ORDER_CLOSED = "WORK_ORDER_CLOSED"
    WATER_BALANCE_PUBLISHED = "WATER_BALANCE_PUBLISHED"


class SyncTargetSystem(str, Enum):
    BILLING = "BILLING"
    GIS = "GIS"
    IM = "IM"


# ---------------------------------------------------------------------------
# Versioned entities (id + created_at + updated_at + version per PRD §2.4)
# ---------------------------------------------------------------------------
class Network(TypedDict, total=False):
    id: str
    name: str
    utility_code: str
    active_topology_version_id: Optional[str]
    nrw_target_pct: float
    clock_epoch_ms: int
    created_at: str
    updated_at: str
    version: int


class TopologyVersion(TypedDict, total=False):
    id: str
    network_id: str
    version_number: int
    status: str
    parent_version_id: Optional[str]
    change_summary: str
    submitted_by: Optional[str]
    reviewed_by: Optional[str]
    published_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DMA(TypedDict, total=False):
    id: str
    network_id: str
    dma_code: str
    name: str
    status: str
    inlet_node_codes: List[str]
    outlet_node_codes: List[str]
    open_critical_alert_count: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    network_id: str
    device_code: str
    mounted_on_node_code: Optional[str]
    protocol: str
    sensor_kind: str
    polling_interval_s: int
    valid_range_min: float
    valid_range_max: float
    status: str
    last_reading_at: Optional[str]
    last_reading_value: Optional[float]
    missed_polls_consecutive: int
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    network_id: str
    dma_id: str
    trigger_device_id: str
    alert_kind: str
    severity: str
    status: str
    first_breach_at: str
    last_breach_at: str
    occurrence_count: int
    baseline_used: Dict[str, Any]
    acknowledged_by: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeakInvestigation(TypedDict, total=False):
    id: str
    alert_id: str
    dma_id: str
    status: str
    water_balance_loss_lps: Optional[float]
    min_night_flow_lps: Optional[float]
    pressure_gradient_anomaly_segments: List[str]
    suspected_segment_codes: List[str]
    assigned_technician_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    network_id: str
    origin: str
    alert_id: Optional[str]
    investigation_id: Optional[str]
    dma_id: str
    target_segment_code: str
    priority: str
    status: str
    assigned_technician_id: Optional[str]
    parts_required: List[Dict[str, Any]]
    started_at: Optional[str]
    completed_at: Optional[str]
    verified_at: Optional[str]
    verification_failure_count: int
    repair_record: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (id + created_at only — NO updated_at, NO version)
# ---------------------------------------------------------------------------
class PipelineNode(TypedDict, total=False):
    id: str
    topology_version_id: str
    node_code: str
    kind: str
    dma_id: Optional[str]
    latitude: float
    longitude: float
    elevation_m: float
    valve_default_open: Optional[bool]
    created_at: str


class PipelineSegment(TypedDict, total=False):
    id: str
    topology_version_id: str
    segment_code: str
    from_node_code: str
    to_node_code: str
    length_m: float
    diameter_mm: int
    material: str
    dma_id: Optional[str]
    created_at: str


class Reading(TypedDict, total=False):
    id: str
    device_id: str
    observed_at: str
    ingested_at: str
    raw_value: float
    validity: str
    archive_tier: str
    idempotency_key: Optional[str]
    created_at: str


class WaterBalanceReport(TypedDict, total=False):
    id: str
    dma_id: str
    window_start: str
    window_end: str
    input_volume_m3: float
    billed_consumption_m3: float
    unbilled_authorized_m3: float
    apparent_loss_m3: float
    real_loss_m3: float
    nrw_pct: float
    published_at: Optional[str]
    created_at: str


class SyncEvent(TypedDict, total=False):
    id: str
    network_id: str
    target_system: str
    event_type: str
    resource_kind: str
    resource_id: str
    payload: Dict[str, Any]
    emitted_at: str
    sequence_no: int
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    network_id: str
    actor_role: str
    actor_id: str
    action: str
    resource_kind: str
    resource_id: str
    detail: Dict[str, Any]
    recorded_at: str
    created_at: str


__all__ = [
    "UserRole",
    "TopologyVersionStatus",
    "DMAStatus",
    "DeviceStatus",
    "AlertStatus",
    "AlertSeverity",
    "AlertKind",
    "LeakInvestigationStatus",
    "WorkOrderStatus",
    "WorkOrderPriority",
    "WorkOrderOrigin",
    "NodeKind",
    "SegmentMaterial",
    "DeviceProtocol",
    "SensorKind",
    "ReadingValidity",
    "ArchiveTier",
    "LeakClass",
    "AuditAction",
    "SyncEventType",
    "SyncTargetSystem",
    "Network",
    "TopologyVersion",
    "DMA",
    "Device",
    "Alert",
    "LeakInvestigation",
    "WorkOrder",
    "PipelineNode",
    "PipelineSegment",
    "Reading",
    "WaterBalanceReport",
    "SyncEvent",
    "AuditLog",
]
