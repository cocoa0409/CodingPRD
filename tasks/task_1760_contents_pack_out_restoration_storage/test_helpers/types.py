"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    INVENTORY_TECHNICIAN = "InventoryTechnician"
    BILLING_CLERK = "BillingClerk"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    SUBCONTRACTOR_CONTACT = "SubcontractorContact"
    CARRIER_REPRESENTATIVE = "CarrierRepresentative"


class JobStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    PACKBACK_IN_PROGRESS = "PACKBACK_IN_PROGRESS"
    CLOSED = "CLOSED"


class StructureStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class BillingStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    INVOICED = "INVOICED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class PolicyCoverageType(str, Enum):
    ACV = "ACV"
    RCV = "RCV"


class RoomType(str, Enum):
    LIVING = "LIVING"
    BEDROOM = "BEDROOM"
    KITCHEN = "KITCHEN"
    BATH = "BATH"
    GARAGE = "GARAGE"
    BASEMENT = "BASEMENT"
    OTHER = "OTHER"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    INVENTORIED = "INVENTORIED"
    CLEARED = "CLEARED"


class ItemCategory(str, Enum):
    TEXTILE = "TEXTILE"
    ELECTRONICS = "ELECTRONICS"
    FURNITURE = "FURNITURE"
    DOCUMENT = "DOCUMENT"
    ARTWORK = "ARTWORK"
    APPLIANCE = "APPLIANCE"
    GENERAL = "GENERAL"


class ConditionTriage(str, Enum):
    PENDING = "PENDING"
    SALVAGEABLE = "SALVAGEABLE"
    NON_SALVAGEABLE = "NON_SALVAGEABLE"


class ProcessingStatus(str, Enum):
    REGISTERED = "REGISTERED"
    AWAITING_CLEANING = "AWAITING_CLEANING"
    IN_CLEANING = "IN_CLEANING"
    CLEANED = "CLEANED"
    IN_STORAGE = "IN_STORAGE"
    OUT_FOR_SPECIALTY = "OUT_FOR_SPECIALTY"
    PACKED_BACK = "PACKED_BACK"
    DELIVERED = "DELIVERED"
    AWAITING_DISPOSAL = "AWAITING_DISPOSAL"
    DISPOSED = "DISPOSED"
    CLAIM_SETTLED = "CLAIM_SETTLED"


TERMINAL_PROCESSING_STATES = (
    ProcessingStatus.DISPOSED.value,
    ProcessingStatus.DELIVERED.value,
    ProcessingStatus.CLAIM_SETTLED.value,
)


class DisposalMethod(str, Enum):
    LANDFILL = "LANDFILL"
    RECYCLE = "RECYCLE"
    HAZARDOUS_WASTE = "HAZARDOUS_WASTE"
    DONATION = "DONATION"


class DisposalRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCUMENTED = "DOCUMENTED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class ProcessCode(str, Enum):
    LAUNDER_DEODORIZE = "LAUNDER_DEODORIZE"
    DRY_CORROSION_INHIBIT = "DRY_CORROSION_INHIBIT"
    SURFACE_CLEAN = "SURFACE_CLEAN"
    FREEZE_DRY = "FREEZE_DRY"
    DEEP_CLEAN = "DEEP_CLEAN"
    STANDARD_CLEAN = "STANDARD_CLEAN"


class CleaningTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ClimateClass(str, Enum):
    CLIMATE_CONTROLLED = "CLIMATE_CONTROLLED"
    STANDARD = "STANDARD"
    COLD_STORAGE = "COLD_STORAGE"


class VaultPosture(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    MANUAL = "MANUAL"
    DISPOSAL = "DISPOSAL"
    CLAIM = "CLAIM"
    SPECIALTY = "SPECIALTY"
    PACK_BACK = "PACK_BACK"


class SpecialtyType(str, Enum):
    ART_CONSERVATION = "ART_CONSERVATION"
    ELECTRONICS_DATA_RECOVERY = "ELECTRONICS_DATA_RECOVERY"
    DOCUMENT_FREEZE_DRYING = "DOCUMENT_FREEZE_DRYING"
    FUR_CLEANING = "FUR_CLEANING"
    JEWELRY_APPRAISAL = "JEWELRY_APPRAISAL"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    IN_CUSTODY = "IN_CUSTODY"
    RETURNED = "RETURNED"
    QA_ACCEPTED = "QA_ACCEPTED"
    QA_REJECTED = "QA_REJECTED"


class CustodyEventType(str, Enum):
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED_BY_SUB = "RECEIVED_BY_SUB"
    RETURNED_BY_SUB = "RETURNED_BY_SUB"
    RECEIVED_BACK = "RECEIVED_BACK"


class ClaimType(str, Enum):
    LOSS = "LOSS"
    DAMAGE = "DAMAGE"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class ScheduleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    INVOICED = "INVOICED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---


class PackOutJob(TypedDict, total=False):
    id: str
    claim_number: str
    property_address: str
    carrier_name: str
    policy_coverage_type: str
    status: str
    structure_status: str
    billing_status: str
    accrued_storage_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    job_id: str
    name: str
    floor_level: int
    room_type: str
    status: str
    item_count: int
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    room_id: str
    barcode: str
    description: str
    item_category: str
    photo_ref: Optional[str]
    declared_value_cents: int
    volume_cu_ft: int
    hazmat_flag: bool
    smoke_damage_flag: bool
    condition_triage: str
    processing_status: str
    is_high_value: bool
    triage_count: int
    created_at: str
    updated_at: str
    version: int


class DisposalRecord(TypedDict, total=False):
    id: str
    item_id: str
    disposal_method: Optional[str]
    manifest_number: Optional[str]
    facility_name: Optional[str]
    photo_ref: Optional[str]
    status: str
    documented_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    documented_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleaningTask(TypedDict, total=False):
    id: str
    item_id: str
    process_code: str
    deodorization_required: bool
    status: str
    rework_count: int
    fee_cents: Optional[int]
    qa_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vault(TypedDict, total=False):
    id: str
    code: str
    climate_class: str
    capacity_cu_ft: int
    monthly_rate_cents_per_cu_ft: int
    occupied_cu_ft: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class StoragePlacement(TypedDict, total=False):
    id: str
    item_id: str
    vault_id: str
    placed_on: str
    released_on: Optional[str]
    release_reason: Optional[str]
    monthly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    name: str
    specialty_types: List[str]
    max_concurrent_referrals: int
    active_referral_count: int
    contact_email: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialtyReferral(TypedDict, total=False):
    id: str
    item_id: str
    subcontractor_id: str
    specialty_type: str
    quoted_cost_cents: int
    markup_pct: int
    billed_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: common_fields false — carries ONLY id + created_at (no updated_at/version).
class CustodyEvent(TypedDict, total=False):
    id: str
    referral_id: str
    event_type: str
    event_at: str
    actor_name: str
    note: Optional[str]
    sequence: int
    created_at: str


class HandlingClaim(TypedDict, total=False):
    id: str
    item_id: str
    claim_type: str
    description: str
    replacement_cost_cents: int
    item_age_years: int
    settlement_variant: Optional[str]
    settlement_amount_cents: Optional[int]
    filed_by_user_id: str
    credited_invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PackBackSchedule(TypedDict, total=False):
    id: str
    job_id: str
    crew_id: str
    service_date: str
    window_start_hour: int
    window_end_hour: int
    status: str
    eligible_item_count: Optional[int]
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class StorageStatement(TypedDict, total=False):
    id: str
    job_id: str
    period_start: str
    period_end: str
    supersedes_statement_id: Optional[str]
    status: str
    provisional_total_cents: int
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CarrierInvoice(TypedDict, total=False):
    id: str
    job_id: str
    adjustment_cents: int
    storage_cents: int
    admin_fee_cents: int
    total_cents: int
    claim_credit_cents: int
    amount_paid_cents: int
    balance_cents: int
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
