"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3 (entities) and §3 state lifecycles. Common-fields rules
follow PRD §2.4: most resources carry id/created_at/updated_at/version, while
the append-only `InstrumentBooking`, `DataModification`, and `AuditEvent`
carry only `id` + `created_at`.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    LAB_CLERK = "LabClerk"
    TESTER = "Tester"
    REVIEWER = "Reviewer"
    SIGNATORY = "Signatory"
    LAB_MANAGER = "LabManager"


# ---------------------------------------------------------------------------
# Domain enumerations (PRD §3.2 / §3.3)
# ---------------------------------------------------------------------------
class MaterialCategory(str, Enum):
    CONCRETE = "CONCRETE"
    STEEL_REBAR = "STEEL_REBAR"
    SOIL = "SOIL"
    ASPHALT = "ASPHALT"
    CEMENT = "CEMENT"


class TestMethod(str, Enum):
    COMPRESSION_STRENGTH = "COMPRESSION_STRENGTH"
    TENSILE_STRENGTH = "TENSILE_STRENGTH"
    COMPACTION_DENSITY = "COMPACTION_DENSITY"
    MARSHALL_STABILITY = "MARSHALL_STABILITY"
    SETTING_TIME = "SETTING_TIME"


# ---------------------------------------------------------------------------
# State enums (PRD §3)
# ---------------------------------------------------------------------------
class SampleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_TESTING = "IN_TESTING"
    RETESTING = "RETESTING"
    TESTED = "TESTED"
    DISPOSED = "DISPOSED"


class TestTaskStatus(str, Enum):
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_RETEST = "AWAITING_RETEST"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TestRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class ReportStatus(str, Enum):
    DRAFTED = "DRAFTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SIGNED = "SIGNED"
    ISSUED = "ISSUED"
    ARCHIVED = "ARCHIVED"
    RECALLED = "RECALLED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class InstrumentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CALIBRATION_DUE = "CALIBRATION_DUE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class InstrumentBookingStatus(str, Enum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QualificationPosture(str, Enum):
    QUALIFIED = "QUALIFIED"
    EXPIRING_SOON = "EXPIRING_SOON"
    LAPSED = "LAPSED"


class AuditEventType(str, Enum):
    REPORT_ISSUED = "REPORT_ISSUED"
    REPORT_RECALLED = "REPORT_RECALLED"
    DATA_MODIFIED = "DATA_MODIFIED"
    EXTERNAL_INSPECTION_RESPONDED = "EXTERNAL_INSPECTION_RESPONDED"
    INTERNAL_AUDIT_RUN = "INTERNAL_AUDIT_RUN"
    QUALIFICATION_LAPSED = "QUALIFICATION_LAPSED"
    INSTRUMENT_CALIBRATION_LAPSED = "INSTRUMENT_CALIBRATION_LAPSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (versioned envelope)
# ---------------------------------------------------------------------------
class Client(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    contract_id: Optional[str]
    deposit_balance_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Qualification(TypedDict):
    material_category: str
    valid_from: str
    valid_to: str


class Tester(TypedDict, total=False):
    id: str
    full_name: str
    qualifications: List[Qualification]
    max_concurrent_tasks: int
    active_task_count: int
    qualification_posture: str
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    full_name: str
    scope_categories: List[str]
    created_at: str
    updated_at: str
    version: int


class Signatory(TypedDict, total=False):
    id: str
    full_name: str
    signature_certificate_id: str
    scope_categories: List[str]
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    asset_code: str
    capabilities: List[str]
    calibration_valid_from: str
    calibration_valid_to: str
    status: str
    usage_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class HandoverRecord(TypedDict):
    delivered_by: str
    received_by: str
    handover_at: str


class Sample(TypedDict, total=False):
    id: str
    client_id: str
    source_project: str
    material_category: str
    specification: str
    witness_sampled: bool
    witness_name: Optional[str]
    sample_code: str
    handover_record: HandoverRecord
    storage_location: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestTask(TypedDict, total=False):
    id: str
    sample_id: str
    test_method: str
    urgent: bool
    assigned_tester_id: Optional[str]
    instrument_booking_id: Optional[str]
    status: str
    retest_count: int
    priority_seq: int
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at (PRD §2.4)
class InstrumentBooking(TypedDict, total=False):
    id: str
    instrument_id: str
    task_id: str
    slot_start: str
    slot_end: str
    status: str
    created_at: str


class TestRecord(TypedDict, total=False):
    id: str
    task_id: str
    tester_id: str
    raw_data: dict
    calculated_result: float
    abnormal_flag: bool
    status: str
    supersedes_record_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at (PRD §2.4)
class DataModification(TypedDict, total=False):
    id: str
    record_id: str
    actor_role: str
    actor_id: str
    field_path: str
    previous_value: str
    new_value: str
    reason: str
    created_at: str


class Report(TypedDict, total=False):
    id: str
    task_id: str
    template_code: str
    reviewer_id: Optional[str]
    signatory_id: Optional[str]
    signature_payload: Optional[str]
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItem(TypedDict):
    task_id: str
    base_fee_cents: int
    surcharge_cents: int
    refund_cents: int


class Invoice(TypedDict, total=False):
    id: str
    client_id: str
    line_items: List[InvoiceLineItem]
    subtotal_cents: int
    surcharge_total_cents: int
    refund_total_cents: int
    package_discount_cents: int
    deposit_applied_cents: int
    total_due_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at (PRD §2.4)
class AuditEvent(TypedDict, total=False):
    id: str
    event_type: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    payload: dict
    created_at: str


__all__ = [
    "UserRole",
    "MaterialCategory",
    "TestMethod",
    "SampleStatus",
    "TestTaskStatus",
    "TestRecordStatus",
    "ReportStatus",
    "InvoiceStatus",
    "InstrumentStatus",
    "InstrumentBookingStatus",
    "QualificationPosture",
    "AuditEventType",
    "Client",
    "Qualification",
    "Tester",
    "Reviewer",
    "Signatory",
    "Instrument",
    "HandoverRecord",
    "Sample",
    "TestTask",
    "InstrumentBooking",
    "TestRecord",
    "DataModification",
    "Report",
    "InvoiceLineItem",
    "Invoice",
    "AuditEvent",
]
