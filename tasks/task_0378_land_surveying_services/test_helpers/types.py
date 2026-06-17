"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the standard system-managed fields id, created_at,
updated_at, and version (see PRD §2.4), so every TypedDict below includes them.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Role enum (X-User-Role values, PRD §2.1) ───────────────────────────
class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    RESEARCHER = "Researcher"
    FIELD_TECH = "FieldTech"
    DRAFTER = "Drafter"
    SURVEYOR = "Surveyor"
    BILLING_CLERK = "BillingClerk"


# ─── Status enums ───────────────────────────────────────────────────────
class CrewRoleType(str, Enum):
    COORDINATOR = "COORDINATOR"
    PLS = "PLS"
    TECH = "TECH"
    RESEARCHER = "RESEARCHER"
    DRAFTER = "DRAFTER"
    BILLING_CLERK = "BILLING_CLERK"


class InstrumentType(str, Enum):
    TOTAL_STATION = "TOTAL_STATION"
    GPS_RTK = "GPS_RTK"
    LEVEL = "LEVEL"
    DRONE = "DRONE"
    SCANNER = "SCANNER"


class InstrumentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    MAINTENANCE = "MAINTENANCE"


class SurveyType(str, Enum):
    BOUNDARY = "BOUNDARY"
    TOPO = "TOPO"
    ALTA = "ALTA"
    ELEVATION = "ELEVATION"


class SurveyOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    RESEARCH = "RESEARCH"
    FIELD_READY = "FIELD_READY"
    IN_FIELD = "IN_FIELD"
    DATA_READY = "DATA_READY"
    DRAFTING = "DRAFTING"
    SEALED = "SEALED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ResearchPacketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    TITLE_HOLD = "TITLE_HOLD"


class FieldAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InstrumentReservationStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class DataSetStatus(str, Enum):
    RAW = "RAW"
    REDUCED = "REDUCED"
    ACCEPTED = "ACCEPTED"


class PlatDrawingStatus(str, Enum):
    DRAFTED = "DRAFTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SEALED = "SEALED"
    IN_REVISION = "IN_REVISION"


class RevisionReason(str, Enum):
    CLIENT_CHANGE = "CLIENT_CHANGE"
    FIELD_ERROR = "FIELD_ERROR"
    DEED_DISCREPANCY = "DEED_DISCREPANCY"


class RevisionRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class DeliverableFormat(str, Enum):
    PDF = "PDF"
    DWG = "DWG"
    PAPER = "PAPER"


class DeliverableStatus(str, Enum):
    ASSEMBLED = "ASSEMBLED"
    RELEASED = "RELEASED"


class InvoiceLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class InvoicePaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


# ─── Entity TypedDicts (all carry common fields per PRD §2.4) ────────────
class CrewMember(TypedDict):
    id: str
    full_name: str
    role_type: str
    license_number: Optional[str]
    license_state: Optional[str]
    license_expires_on: Optional[str]
    active: bool
    open_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict):
    id: str
    asset_tag: str
    instrument_type: str
    calibration_due_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyOrder(TypedDict):
    id: str
    client_name: str
    survey_type: str
    parcel_apn: str
    county_fips: str
    acreage: float
    rush: bool
    requested_due_date: str
    status: str
    research_clear: bool
    base_fee_cents: int
    estimated_fee_cents: int
    final_fee_cents: int
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class ResearchPacket(TypedDict):
    id: str
    order_id: str
    assigned_researcher_id: str
    deed_book: Optional[str]
    deed_page: Optional[str]
    encumbrance_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FieldAssignment(TypedDict):
    id: str
    order_id: str
    crew_member_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    window_minutes: int
    created_at: str
    updated_at: str
    version: int


class InstrumentReservation(TypedDict):
    id: str
    assignment_id: str
    instrument_id: str
    reserved_start: str
    reserved_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DataSet(TypedDict):
    id: str
    order_id: str
    assignment_id: str
    recorded_by_id: str
    point_count: int
    closure_error_ppm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlatDrawing(TypedDict):
    id: str
    order_id: str
    dataset_id: str
    drafted_by_id: str
    sealed_by_id: Optional[str]
    status: str
    sealed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict):
    id: str
    plat_id: str
    reason: str
    notes: Optional[str]
    status: str
    reseal_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    order_id: str
    plat_id: str
    format: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    order_id: str
    issued_by_id: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    lifecycle_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int
