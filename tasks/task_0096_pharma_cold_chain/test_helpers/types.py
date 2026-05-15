"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: Warehouse, Zone, Bin, Supplier, Product, InboundReceipt, Lot,
OutboundShipment, Deviation, CAPA, Recall carry id, created_at,
updated_at, and version. Four families are append-only and carry only
id and created_at: TemperatureEvent, RecallScopeEntry, ExternalSyncEvent,
AuditLogEntry — their TypedDicts MUST omit updated_at and version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    WAREHOUSE_ADMIN = "WarehouseAdmin"
    RECEIVER = "Receiver"
    QA_OFFICER = "QAOfficer"
    PICKER = "Picker"
    RECALL_OFFICER = "RecallOfficer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class WarehouseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ZoneType(str, Enum):
    FROZEN = "FROZEN"
    REFRIGERATED = "REFRIGERATED"
    COOL = "COOL"
    ROOM_TEMP = "ROOM_TEMP"
    CONTROLLED_TEMP = "CONTROLLED_TEMP"
    QUARANTINE = "QUARANTINE"


class ZonePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class BinStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    LOCKED = "LOCKED"


class SpecialStorageTag(str, Enum):
    NONE = "NONE"
    NARCOTIC = "NARCOTIC"
    PSYCHOTROPIC = "PSYCHOTROPIC"
    BIOLOGICAL = "BIOLOGICAL"
    VACCINE = "VACCINE"


class ReceiptStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    INSPECTED = "INSPECTED"
    QUARANTINED = "QUARANTINED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class NonconformanceReason(str, Enum):
    NONE = "NONE"
    UNQUALIFIED_SUPPLIER = "UNQUALIFIED_SUPPLIER"
    UNQUALIFIED_PRODUCT = "UNQUALIFIED_PRODUCT"
    VISUAL_FAIL = "VISUAL_FAIL"
    TEMP_EXCURSION = "TEMP_EXCURSION"
    EXPIRED_ON_ARRIVAL = "EXPIRED_ON_ARRIVAL"


class LotQualityStatus(str, Enum):
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    PICKED = "PICKED"
    PACKED = "PACKED"
    DISPATCHED = "DISPATCHED"
    QUARANTINED = "QUARANTINED"
    CANCELLED = "CANCELLED"


class PackagingKind(str, Enum):
    INSULATED_PCM = "INSULATED_PCM"
    INSULATED_DRY_ICE = "INSULATED_DRY_ICE"
    AMBIENT = "AMBIENT"


class TemperatureEventKind(str, Enum):
    IN_RANGE = "IN_RANGE"
    WARNING_LOW = "WARNING_LOW"
    WARNING_HIGH = "WARNING_HIGH"
    ALARM_LOW = "ALARM_LOW"
    ALARM_HIGH = "ALARM_HIGH"


class DeviationClassification(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DeviationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_PENDING_QA = "CLOSED_PENDING_QA"
    CLOSED_ASSESSED = "CLOSED_ASSESSED"


class QaDecision(str, Enum):
    PENDING = "PENDING"
    RELEASE = "RELEASE"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


class CapaStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


class RecallClassification(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    RETURNS_IN_PROGRESS = "RETURNS_IN_PROGRESS"
    EFFECTIVENESS_CHECK = "EFFECTIVENESS_CHECK"
    CLOSED = "CLOSED"


class RecallScopeKind(str, Enum):
    ON_HAND = "ON_HAND"
    SHIPPED = "SHIPPED"


class ExternalTargetSystem(str, Enum):
    REGULATORY_AUTHORITY = "REGULATORY_AUTHORITY"
    GSP_REPORT = "GSP_REPORT"
    PHARMACOVIGILANCE = "PHARMACOVIGILANCE"
    TMS = "TMS"


class ExternalEventType(str, Enum):
    INBOUND_ACCEPTED = "INBOUND_ACCEPTED"
    INBOUND_QUARANTINED = "INBOUND_QUARANTINED"
    DEVIATION_OPENED = "DEVIATION_OPENED"
    DEVIATION_CLOSED = "DEVIATION_CLOSED"
    RECALL_ANNOUNCED = "RECALL_ANNOUNCED"
    RECALL_CLOSED = "RECALL_CLOSED"
    SHIPMENT_DISPATCHED = "SHIPMENT_DISPATCHED"
    CAPA_OVERDUE = "CAPA_OVERDUE"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true → id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Warehouse(TypedDict, total=False):
    id: str
    code: str
    name: str
    gsp_license_no: str
    clock_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    warehouse_id: str
    code: str
    zone_type: str
    target_temp_low_c: float
    target_temp_high_c: float
    alarm_low_c: float
    alarm_high_c: float
    current_posture: str
    last_sensor_reading_c: Optional[float]
    capacity_units: int
    utilization_units: int
    created_at: str
    updated_at: str
    version: int


class Bin(TypedDict, total=False):
    id: str
    zone_id: str
    warehouse_id: str
    code: str
    volume_units: int
    weight_limit_kg: float
    special_storage_tag: str
    current_lot_id: Optional[str]
    occupied_volume: int
    occupied_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    name: str
    qualified: bool
    qualification_expiry_minutes: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    required_zone_type: str
    special_storage_tag: str
    qualified: bool
    unit_weight_kg: float
    stability_budget_minutes: int
    created_at: str
    updated_at: str
    version: int


class InboundReceipt(TypedDict, total=False):
    id: str
    warehouse_id: str
    supplier_id: str
    product_id: str
    lot_number: str
    expiry_minutes: int
    quantity_units: int
    carrier_logger_readings: List[dict]
    visual_pass: bool
    temp_chain_intact: Optional[bool]
    nonconformance_reason: Optional[str]
    assigned_bin_id: Optional[str]
    acceptance_certificate_no: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    warehouse_id: str
    product_id: str
    supplier_id: str
    lot_number: str
    expiry_minutes: int
    receipt_id: str
    quantity_on_hand: int
    quantity_picked: int
    bin_id: Optional[str]
    cumulative_excursion_minutes: int
    quality_status: str
    created_at: str
    updated_at: str
    version: int


class OutboundShipment(TypedDict, total=False):
    id: str
    warehouse_id: str
    customer_id: str
    product_id: str
    quantity_units: int
    packaging_kind: str
    pick_lot_id: Optional[str]
    pick_temp_c: float
    vehicle_precondition_temp_c: float
    logger_armed: bool
    dispatched_at_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deviation(TypedDict, total=False):
    id: str
    zone_id: str
    warehouse_id: str
    started_at_minutes: int
    ended_at_minutes: Optional[int]
    max_magnitude_c: float
    duration_minutes: int
    classification: Optional[str]
    qa_decision: str
    capa_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CAPA(TypedDict, total=False):
    id: str
    warehouse_id: str
    deviation_id: Optional[str]
    recall_id: Optional[str]
    due_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict, total=False):
    id: str
    warehouse_id: str
    classification: str
    reason: str
    initiated_at_minutes: Optional[int]
    report_due_minutes: Optional[int]
    notifications_required: Optional[int]
    notifications_sent: int
    returns_expected_units: Optional[int]
    returns_received_units: int
    effectiveness_pass: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only TypedDicts — id + created_at ONLY (common_fields: false)
# Per PRD §2.4 these entities MUST NOT carry updated_at or version.
# ---------------------------------------------------------------------------
class TemperatureEvent(TypedDict, total=False):
    id: str
    zone_id: str
    warehouse_id: str
    at_minutes: int
    temp_c: float
    kind: str
    deviation_id: Optional[str]
    created_at: str


class RecallScopeEntry(TypedDict, total=False):
    id: str
    recall_id: str
    lot_id: str
    shipment_id: Optional[str]
    scope_kind: str
    units: int
    created_at: str


class ExternalSyncEvent(TypedDict, total=False):
    id: str
    warehouse_id: str
    target_system: str
    event_type: str
    payload: dict
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    warehouse_id: str
    actor_user_id: str
    actor_role: str
    action: str
    target_id: str
    at_minutes: int
    created_at: str


__all__ = [
    "UserRole",
    "WarehouseStatus",
    "ZoneType",
    "ZonePosture",
    "BinStatus",
    "SpecialStorageTag",
    "ReceiptStatus",
    "NonconformanceReason",
    "LotQualityStatus",
    "ShipmentStatus",
    "PackagingKind",
    "TemperatureEventKind",
    "DeviationClassification",
    "DeviationStatus",
    "QaDecision",
    "CapaStatus",
    "RecallClassification",
    "RecallStatus",
    "RecallScopeKind",
    "ExternalTargetSystem",
    "ExternalEventType",
    "Warehouse",
    "Zone",
    "Bin",
    "Supplier",
    "Product",
    "InboundReceipt",
    "Lot",
    "OutboundShipment",
    "Deviation",
    "CAPA",
    "Recall",
    "TemperatureEvent",
    "RecallScopeEntry",
    "ExternalSyncEvent",
    "AuditLogEntry",
]
