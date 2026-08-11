"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any, Dict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_CLERK = "IntakeClerk"
    PREP_TECHNICIAN = "PrepTechnician"
    SCAN_OPERATOR = "ScanOperator"
    QA_REVIEWER = "QAReviewer"
    INDEXER = "Indexer"
    DESTRUCTION_SPECIALIST = "DestructionSpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BILLING_CLERK = "BillingClerk"
    CLIENT_USER = "ClientUser"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BatchStatus(str, Enum):
    INTAKE = "INTAKE"
    PREPPING = "PREPPING"
    SCANNING = "SCANNING"
    QA = "QA"
    INDEXING = "INDEXING"
    DELIVERED = "DELIVERED"
    DISPOSITION_PENDING = "DISPOSITION_PENDING"
    CLOSED = "CLOSED"


class BatchPriority(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class BoxStatus(str, Enum):
    RECEIVED = "RECEIVED"
    STORED = "STORED"
    IN_PREP = "IN_PREP"
    IN_SCAN = "IN_SCAN"
    SCAN_COMPLETE = "SCAN_COMPLETE"
    AWAITING_DISPOSITION = "AWAITING_DISPOSITION"
    IN_DESTRUCTION = "IN_DESTRUCTION"
    DESTROYED = "DESTROYED"
    RETURNED = "RETURNED"


class DocumentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SCANNED = "SCANNED"
    QA_FAILED = "QA_FAILED"
    INDEXED = "INDEXED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class DocType(str, Enum):
    MEDICAL_RECORD = "MEDICAL_RECORD"
    INVOICE = "INVOICE"
    CONTRACT = "CONTRACT"
    CORRESPONDENCE = "CORRESPONDENCE"
    OTHER = "OTHER"


class ScanSessionStatus(str, Enum):
    OPEN = "OPEN"
    COMMITTED = "COMMITTED"
    VOIDED = "VOIDED"


class AccessGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AccessGrantScope(str, Enum):
    METADATA_ONLY = "METADATA_ONLY"
    FULL_IMAGE = "FULL_IMAGE"


class DestructionMethod(str, Enum):
    SHRED = "SHRED"
    INCINERATE = "INCINERATE"
    PULP = "PULP"


class ScannerUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class ShelfZone(str, Enum):
    GENERAL = "GENERAL"
    VAULT = "VAULT"


class ShelfAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class PriceTier(str, Enum):
    STANDARD = "STANDARD"
    VOLUME = "VOLUME"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true entities carry id + created_at + updated_at + version.
# common_fields: false entities (PageLog, CustodyEvent) carry only id + created_at.
# ---------------------------------------------------------------------------

class Client(TypedDict, total=False):
    id: str
    name: str
    hipaa_covered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAgreement(TypedDict, total=False):
    id: str
    client_id: str
    price_tier: str
    rush_multiplier: float
    storage_free_days: int
    storage_daily_rate_cents: int
    retention_days: int
    max_boxes_per_batch: int
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict, total=False):
    id: str
    client_id: str
    priority: str
    status: str
    scanned_pages: int
    billable_scanned_pages: int
    rework_cycle_count: int
    delivery_status: str
    delivered_at: Optional[str]
    disposition_at: Optional[str]
    projected_storage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Box(TypedDict, total=False):
    id: str
    batch_id: str
    box_label: str
    intake_weight_grams: int
    status: str
    return_requested: bool
    custody_flagged: bool
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict, total=False):
    id: str
    box_id: str
    batch_id: str
    doc_type: str
    pages: int
    contains_phi: bool
    ocr_confidence: int
    status: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScanSession(TypedDict, total=False):
    id: str
    batch_id: str
    scanner_id: str
    operator_id: str
    status: str
    page_count: int
    started_at: str
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PageLog(TypedDict, total=False):
    """Append-only: only id + created_at are universal; NO updated_at / version."""
    id: str
    session_id: str
    batch_id: str
    document_id: str
    pages: int
    created_at: str


class IndexRecord(TypedDict, total=False):
    id: str
    document_id: str
    batch_id: str
    metadata_json: Dict[str, Any]
    ocr_text_ref: str
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    client_id: str
    batch_id: str
    scope: str
    expires_at: str
    vault_only: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CustodyEvent(TypedDict, total=False):
    """Append-only: only id + created_at are universal; NO updated_at / version."""
    id: str
    box_id: str
    from_stage: str
    to_stage: str
    actor_user_id: str
    actor_role: str
    notes: Optional[str]
    created_at: str


class DestructionCertificate(TypedDict, total=False):
    id: str
    box_id: str
    batch_id: str
    witness_user_id: str
    method: str
    certificate_code: str
    destroyed_at: str
    created_at: str
    updated_at: str
    version: int


class ScannerUnit(TypedDict, total=False):
    id: str
    scanner_code: str
    capacity_pages_per_session: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShelfSlot(TypedDict, total=False):
    id: str
    shelf_code: str
    zone: str
    capacity_grams: int
    occupied_weight_grams: int
    created_at: str
    updated_at: str
    version: int


class ShelfAssignment(TypedDict, total=False):
    id: str
    box_id: str
    shelf_slot_id: str
    placed_at: str
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    batch_id: str
    client_id: str
    status: str
    page_subtotal_cents: int
    storage_subtotal_cents: int
    total_cents: int
    amount_paid_cents: int
    issued_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
