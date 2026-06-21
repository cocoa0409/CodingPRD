"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and lifecycles described in the Product Recall & Field
Action PRD (Sections 2.4, 3.x). Primary resources carry the common system
fields (id, created_at, updated_at, version); the immutable AffectedLot
junction row carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    CLASSIFIED = "CLASSIFIED"
    ANNOUNCED = "ANNOUNCED"
    MONITORING = "MONITORING"
    EFFECTIVE = "EFFECTIVE"
    TERMINATED = "TERMINATED"


class RecallClassification(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class Regulator(str, Enum):
    FDA = "FDA"
    CPSC = "CPSC"


class HazardSeverity(str, Enum):
    SERIOUS = "SERIOUS"
    TEMPORARY = "TEMPORARY"
    MINOR = "MINOR"


class QuarantineStatus(str, Enum):
    RELEASED = "RELEASED"
    HELD = "HELD"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ContactChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    MAIL = "MAIL"


class NotificationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"


class DispositionType(str, Enum):
    RETURN = "RETURN"
    REPLACE = "REPLACE"
    REFUND = "REFUND"


class LogisticsStatus(str, Enum):
    PENDING = "PENDING"
    RETURNED = "RETURNED"
    REPLACED = "REPLACED"
    CANCELLED = "CANCELLED"


class FinancialStatus(str, Enum):
    NOT_OWED = "NOT_OWED"
    OWED = "OWED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class RefundBasis(str, Enum):
    SALE_PRICE = "SALE_PRICE"
    LIST_PRICE = "LIST_PRICE"


class ReportKind(str, Enum):
    INITIAL = "INITIAL"
    FOLLOWUP = "FOLLOWUP"
    FINAL = "FINAL"


class ReportStatus(str, Enum):
    DRAFTED = "DRAFTED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class CheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class UserRole(str, Enum):
    RECALL_COORDINATOR = "RecallCoordinator"
    QUALITY_OFFICER = "QualityOfficer"
    FIELD_SERVICE_AGENT = "FieldServiceAgent"
    FINANCE_CLERK = "FinanceClerk"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Entity TypedDicts — primary resources carry id/created_at/updated_at/version
# --------------------------------------------------------------------------
class Product(TypedDict):
    id: str
    sku: str
    name: str
    regulator: str
    unit_list_price_cents: int
    active_recall_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    product_id: str
    lot_code: str
    serial_start: int
    serial_end: int
    manufactured_units: int
    quarantine_status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    lot_id: str
    serial_number: int
    customer_id: str
    sale_price_cents: int
    affected: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    contact_channel: str
    contact_address: str
    reachable: bool
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    product_id: str
    reason: str
    hazard_severity: str
    injury_reported: bool
    serial_filter_start: Optional[int]
    serial_filter_end: Optional[int]
    classification: Optional[str]
    classified_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    notification_deadline_hours: Optional[int]
    affected_unit_count: int
    recovered_unit_count: int
    effectiveness_pct: float
    total_refund_cents: int
    created_at: str
    updated_at: str
    version: int


# AffectedLot is the immutable junction row: id + created_at only.
class AffectedLot(TypedDict):
    id: str
    recall_id: str
    lot_id: str
    unit_count_snapshot: int
    created_at: str


class QuarantineHold(TypedDict):
    id: str
    recall_id: str
    lot_id: str
    reason: str
    status: str
    lifted_count: int
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict):
    id: str
    recall_id: str
    customer_id: str
    channel: str
    status: str
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict):
    id: str
    recall_id: str
    unit_id: str
    disposition_type: str
    logistics_status: str
    financial_status: str
    refund_basis: str
    refund_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict):
    id: str
    recall_id: str
    agency: str
    report_kind: str
    filed_within_deadline: bool
    status: str
    signed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EffectivenessCheck(TypedDict):
    id: str
    recall_id: str
    target_pct: float
    measured_pct: float
    outcome: str
    created_at: str
    updated_at: str
    version: int
