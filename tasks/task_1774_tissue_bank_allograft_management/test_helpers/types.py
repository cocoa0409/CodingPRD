"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COORDINATOR = "TissueBankCoordinator"
    QUALITY_MANAGER = "QualityManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    IMPLANTING_SURGEON = "ImplantingSurgeon"
    SUPPLY_CHAIN_ADMIN = "SupplyChainAdmin"


class SupplierStatus(str, Enum):
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class DocumentType(str, Enum):
    AATB_ACCREDITATION = "AATB_ACCREDITATION"
    FDA_REGISTRATION = "FDA_REGISTRATION"
    STATE_LICENSE = "STATE_LICENSE"
    ISO_CERTIFICATE = "ISO_CERTIFICATE"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ShipmentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class TissueType(str, Enum):
    BONE = "BONE"
    SOFT_TISSUE = "SOFT_TISSUE"
    CARDIOVASCULAR = "CARDIOVASCULAR"
    SKIN = "SKIN"
    CORNEA = "CORNEA"


class CriticalityTier(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    CRITICAL = "CRITICAL"


class UnitStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    IMPLANTED = "IMPLANTED"
    DISCARDED = "DISCARDED"
    RETURNED_TO_SUPPLIER = "RETURNED_TO_SUPPLIER"
    EXPIRED = "EXPIRED"


class HoldReason(str, Enum):
    NONE = "NONE"
    EXCURSION = "EXCURSION"
    RECALL = "RECALL"
    MANUAL = "MANUAL"


class FreezerStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    EXCURSION_ACTIVE = "EXCURSION_ACTIVE"


class ExcursionOrigin(str, Enum):
    AUTO_READING = "AUTO_READING"
    MANUAL_REPORT = "MANUAL_REPORT"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED_RELEASE = "RESOLVED_RELEASE"
    RESOLVED_DESTROY = "RESOLVED_DESTROY"


class SeverityClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"


class ReleaseReason(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    EXCURSION = "EXCURSION"
    RECALL = "RECALL"
    CASE_CANCELLED = "CASE_CANCELLED"
    CASE_COMPLETED = "CASE_COMPLETED"
    CLOCK_EXPIRED = "CLOCK_EXPIRED"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ClosureReason(str, Enum):
    NONE = "NONE"
    NO_MATCH = "NO_MATCH"
    RESOLVED = "RESOLVED"


class ReactionType(str, Enum):
    INFECTION = "INFECTION"
    REJECTION = "REJECTION"
    OTHER = "OTHER"


class ReactionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AdverseStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CLOSED_CONFIRMED = "CLOSED_CONFIRMED"
    CLOSED_UNCONFIRMED = "CLOSED_UNCONFIRMED"
    REOPENED = "REOPENED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DispositionType(str, Enum):
    IMPLANTED = "IMPLANTED"
    DESTROYED = "DESTROYED"
    RETURNED_TO_SUPPLIER = "RETURNED_TO_SUPPLIER"
    EXPIRED = "EXPIRED"


class DispositionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class ValuationMethod(str, Enum):
    FIFO = "FIFO"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"


# --- Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version) ---


class Supplier(TypedDict):
    id: str
    legal_name: str
    license_number: str
    status: str
    qualification_score_provisional: float
    qualification_score_final: float
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplierDocument(TypedDict):
    id: str
    supplier_id: str
    doc_type: str
    document_ref: str
    valid_from: str
    valid_to: str
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    supplier_id: str
    freezer_id: str
    items: List[dict]
    status: str
    received_at: str
    total_declared_value_cents: int
    unit_count: int
    accepted_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TissueUnit(TypedDict):
    id: str
    shipment_id: str
    supplier_id: str
    freezer_id: str
    tissue_type: str
    lot_number: str
    serial_number: str
    unit_cost_cents: int
    criticality_tier: str
    expiration_at: str
    received_at: str
    status: str
    hold_reason: str
    recall_flag: bool
    implanted_case_id: Optional[str]
    implanted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Freezer(TypedDict):
    id: str
    name: str
    min_celsius: float
    max_celsius: float
    nominal_capacity: int
    status: str
    occupied_count: int
    utilization_pct: float
    quarantine_reserve_slots: int
    effective_capacity: int
    current_excursion_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only observation: id + created_at only,
# NO updated_at and NO version (PRD §2.5).
class TemperatureReading(TypedDict):
    id: str
    freezer_id: str
    temp_celsius: float
    in_range: bool
    recorded_by_user_id: str
    excursion_id: Optional[str]
    created_at: str


class TemperatureExcursion(TypedDict):
    id: str
    freezer_id: str
    origin: str
    status: str
    opened_at: str
    last_reading_at: Optional[str]
    max_deviation_celsius: float
    affected_unit_count: int
    severity_score: int
    severity_class: str
    reported_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_notes: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImplantCase(TypedDict):
    id: str
    surgeon_id: str
    patient_ref: str
    or_room_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    implanted_unit_count: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    implant_case_id: str
    tissue_unit_id: str
    status: str
    hold_until: str
    release_reason: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    supplier_id: str
    lot_numbers: List[str]
    received_window_start: str
    received_window_end: str
    reason: str
    status: str
    closure_reason: str
    affected_unit_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdverseReactionCase(TypedDict):
    id: str
    implant_case_id: str
    tissue_unit_id: str
    reporter_user_id: str
    reaction_type: str
    severity: str
    description: str
    status: str
    investigator_user_id: Optional[str]
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class ParLevelPolicy(TypedDict):
    id: str
    tissue_type: str
    par_quantity: int
    max_inventory_value_cents: int
    status: str
    on_hand_available: int
    deficit: int
    needs_reorder: bool
    created_at: str
    updated_at: str
    version: int


class DispositionRecord(TypedDict):
    id: str
    tissue_unit_id: str
    disposition_type: str
    reason: str
    recorded_by_user_id: str
    status: str
    finalized_at: Optional[str]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
