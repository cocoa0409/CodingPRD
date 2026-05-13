"""Domain types: status enums, role enum, and entity TypedDicts.

Field membership is derived from the PRD §2.4 (common properties) and
§3.x entity sections. Entities that 'exist as immutable lifecycle
artefacts' (PRD §2.4: HandoverRecord, ResponseAction, TemperatureReading,
AuditLogEntry) carry only id + created_at — no updated_at and no version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SHIPPER = "SHIPPER"
    CARRIER = "CARRIER"
    DRIVER = "DRIVER"
    CONSIGNEE = "CONSIGNEE"
    DISPATCHER = "DISPATCHER"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    INSURANCE_ADJUSTER = "INSURANCE_ADJUSTER"
    SYSTEM = "SYSTEM"


# ---------------------------------------------------------------------------
# Entity status enums (PRD §3.x)
# ---------------------------------------------------------------------------
class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DriverStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    ON_DUTY = "ON_DUTY"
    SUSPENDED = "SUSPENDED"


class TransportTaskStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_STOP = "AT_STOP"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"


class TaskStopStatus(str, Enum):
    PENDING = "PENDING"
    ARRIVED = "ARRIVED"
    HANDED_OVER = "HANDED_OVER"
    SKIPPED = "SKIPPED"


class CargoType(str, Enum):
    FOOD = "FOOD"
    PHARMACEUTICAL = "PHARMACEUTICAL"
    BIOLOGICAL = "BIOLOGICAL"


class SensorKind(str, Enum):
    COMPARTMENT = "COMPARTMENT"
    CARGO_BOX = "CARGO_BOX"


class ReadingValidity(str, Enum):
    VALID = "VALID"
    INVALID_OUT_OF_WINDOW = "INVALID_OUT_OF_WINDOW"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    ARCHIVED = "ARCHIVED"


class Violation(str, Enum):
    WITHIN = "WITHIN"
    BELOW_MIN = "BELOW_MIN"
    ABOVE_MAX = "ABOVE_MAX"


class AlertLevel(str, Enum):
    WARNING = "WARNING"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_RESPONSE = "IN_RESPONSE"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class NotifyChannel(str, Enum):
    DRIVER = "DRIVER"
    DISPATCH = "DISPATCH"
    CUSTOMER = "CUSTOMER"


class ActionKind(str, Enum):
    VENTILATION = "VENTILATION"
    REFRIGERATION_ADJUSTMENT = "REFRIGERATION_ADJUSTMENT"
    TRANSSHIPMENT = "TRANSSHIPMENT"
    INSPECTION = "INSPECTION"


class DamageClass(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    TOTAL_LOSS = "TOTAL_LOSS"


class CausePrimary(str, Enum):
    TEMPERATURE_DEVIATION = "TEMPERATURE_DEVIATION"
    DURATION = "DURATION"
    CARGO_SENSITIVITY = "CARGO_SENSITIVITY"
    OTHER = "OTHER"


class DamageVariant(str, Enum):
    INSURED_VALUE = "INSURED_VALUE"
    INVOICE_VALUE = "INVOICE_VALUE"


class DamageAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class SplitMethod(str, Enum):
    DURATION_WEIGHTED = "DURATION_WEIGHTED"
    SEVERITY_WEIGHTED = "SEVERITY_WEIGHTED"


class ResponsibilityDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    MEDIATION = "MEDIATION"
    ACCEPTED = "ACCEPTED"
    FINALIZED = "FINALIZED"


class InsuranceClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    EVIDENCE_PREP = "EVIDENCE_PREP"
    ASSESSMENT = "ASSESSMENT"
    NEGOTIATING = "NEGOTIATING"
    REJECTED = "REJECTED"
    PAID_OUT = "PAID_OUT"
    SUBROGATION = "SUBROGATION"
    CLOSED = "CLOSED"


class ComplianceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class AuditSubjectType(str, Enum):
    ALERT = "ALERT"
    RESPONSIBILITY_DECISION = "RESPONSIBILITY_DECISION"


class AuditAction(str, Enum):
    OPENED = "OPENED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESPONSE_RECORDED = "RESPONSE_RECORDED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    DRAFTED = "DRAFTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    MEDIATED = "MEDIATED"
    ACCEPTED = "ACCEPTED"
    FINALIZED = "FINALIZED"


# ===========================================================================
# Entity TypedDicts — common_fields: true (id + created_at + updated_at + version)
# ===========================================================================
class Vehicle(TypedDict, total=False):
    id: str
    vehicle_no: str
    compartment_count: int
    insured_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    license_no: str
    name: str
    max_daily_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportTask(TypedDict, total=False):
    id: str
    cargo_type: str
    cargo_value_cents: int
    cargo_quantity: int
    temp_min_celsius: float
    temp_max_celsius: float
    shipper_id: str
    consignee_id: str
    carrier_id: str
    vehicle_id: Optional[str]
    driver_id: Optional[str]
    planned_start_at: str
    planned_end_at: str
    polling_interval_seconds: int
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaskStop(TypedDict, total=False):
    id: str
    task_id: str
    sequence: int
    location_label: str
    planned_arrival_at: str
    actual_arrival_at: Optional[str]
    status: str
    handover_required: bool
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    task_id: str
    opening_reading_id: str
    violation: str
    level: str
    duration_seconds: int
    peak_deviation_celsius: float
    notified_channels: List[str]
    status: str
    opened_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict, total=False):
    id: str
    task_id: str
    damaged_quantity: int
    damage_class: str
    salvage_pct: float
    cause_primary: str
    evidence_alert_ids: List[str]
    damage_amount_cents: int
    variant: str
    invoice_unit_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResponsibilityDecision(TypedDict, total=False):
    id: str
    task_id: str
    assessment_id: str
    shipper_pct: float
    carrier_pct: float
    consignee_pct: float
    attributed_quantity: Optional[int]
    split_method: str
    status: str
    mediator_id: Optional[str]
    finalizing_role: Optional[str]
    advisory_split: dict
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    task_id: str
    decision_id: str
    requested_amount_cents: int
    assessed_amount_cents: Optional[int]
    payout_amount_cents: Optional[int]
    subrogation_recovered_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict, total=False):
    id: str
    regulatory_domain: str
    period_start: str
    period_end: str
    task_count: int
    alert_count: int
    critical_alert_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only entities (PRD §2.4) — id + created_at ONLY
# ===========================================================================
class HandoverRecord(TypedDict, total=False):
    id: str
    stop_id: str
    task_id: str
    from_party_id: str
    to_party_id: str
    temperature_at_handover_celsius: float
    quantity_attested: int
    photo_evidence_ref: str
    handed_over_at: str
    created_at: str


class ResponseAction(TypedDict, total=False):
    id: str
    alert_id: str
    action_kind: str
    executed_by_role: str
    notes: Optional[str]
    executed_at: str
    created_at: str


class TemperatureReading(TypedDict, total=False):
    id: str
    task_id: str
    sensor_id: str
    sensor_kind: str
    temperature_celsius: float
    gps_lat: float
    gps_lng: float
    captured_at: str
    idempotency_key: str
    validity: str
    violation: str
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "VehicleStatus", "DriverStatus",
    "TransportTaskStatus", "TaskStopStatus", "CargoType",
    "SensorKind", "ReadingValidity", "Violation",
    "AlertLevel", "AlertStatus", "NotifyChannel", "ActionKind",
    "DamageClass", "CausePrimary", "DamageVariant", "DamageAssessmentStatus",
    "SplitMethod", "ResponsibilityDecisionStatus",
    "InsuranceClaimStatus", "ComplianceReportStatus",
    "AuditSubjectType", "AuditAction",
    "Vehicle", "Driver", "TransportTask", "TaskStop", "Alert",
    "DamageAssessment", "ResponsibilityDecision",
    "InsuranceClaim", "ComplianceReport",
    "HandoverRecord", "ResponseAction", "TemperatureReading", "AuditLogEntry",
]
