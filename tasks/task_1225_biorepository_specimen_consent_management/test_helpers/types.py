"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class DonorStatus(str, Enum):
    ENROLLED = "ENROLLED"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWAL_PENDING = "WITHDRAWAL_PENDING"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class KitType(str, Enum):
    BLOOD = "BLOOD"
    SALIVA = "SALIVA"
    TISSUE = "TISSUE"


class KitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    DISTRIBUTED = "DISTRIBUTED"
    RETURNED = "RETURNED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class CustodyEventType(str, Enum):
    DISTRIBUTED = "DISTRIBUTED"
    RETURNED = "RETURNED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class SpecimenType(str, Enum):
    BLOOD = "BLOOD"
    SALIVA = "SALIVA"
    TISSUE = "TISSUE"
    PLASMA = "PLASMA"


class SpecimenLifecycle(str, Enum):
    ACCESSIONED = "ACCESSIONED"
    IN_STORAGE = "IN_STORAGE"
    DESTRUCTION_PENDING = "DESTRUCTION_PENDING"
    DESTROYED = "DESTROYED"


class ViabilityStatus(str, Enum):
    USABLE = "USABLE"
    QUARANTINED = "QUARANTINED"


class AliquotStatus(str, Enum):
    IN_STORAGE = "IN_STORAGE"
    RESERVED = "RESERVED"
    QUARANTINED = "QUARANTINED"
    DESTRUCTION_PENDING = "DESTRUCTION_PENDING"
    DISTRIBUTED = "DISTRIBUTED"
    DESTROYED = "DESTROYED"
    VOID = "VOID"


class UnitPosture(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    WARNING = "WARNING"
    FAILURE = "FAILURE"


class SlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFFLINE = "OFFLINE"


class ReservationPurpose(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    TRANSFER_HOLD = "TRANSFER_HOLD"
    AUDIT = "AUDIT"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    COMPROMISED = "COMPROMISED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class VoteDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class KeyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class DestructionReason(str, Enum):
    CONSENT_WITHDRAWAL = "CONSENT_WITHDRAWAL"
    QUALITY_FAILURE = "QUALITY_FAILURE"
    OTHER = "OTHER"


class DestructionOrderStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class ConsentUse(str, Enum):
    GENERAL_RESEARCH = "GENERAL_RESEARCH"
    DISEASE_SPECIFIC = "DISEASE_SPECIFIC"
    GENETIC_ANALYSIS = "GENETIC_ANALYSIS"
    COMMERCIAL_USE = "COMMERCIAL_USE"


class UserRole(str, Enum):
    BIOBANK_ADMIN = "BiobankAdmin"
    CONSENT_COORDINATOR = "ConsentCoordinator"
    LAB_TECHNICIAN = "LabTechnician"
    COMMITTEE_REVIEWER = "CommitteeReviewer"
    RESEARCHER = "Researcher"
    QUALITY_OFFICER = "QualityOfficer"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Donor(TypedDict, total=False):
    id: str
    donor_reference_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    donor_id: str
    permitted_uses: List[str]
    excluded_uses: List[str]
    allow_reidentification: bool
    effective_from: str
    status: str
    withdrawal_requested_at: Optional[str]
    grace_deadline: Optional[str]
    supersedes_consent_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollectionKit(TypedDict, total=False):
    id: str
    kit_type: str
    donor_id: Optional[str]
    expires_at: str
    status: str
    distributed_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# CustodyEvent is an immutable audit record: only id + created_at, no updated_at/version.
class CustodyEvent(TypedDict, total=False):
    id: str
    kit_id: str
    event_type: str
    actor_user_id: str
    location: Optional[str]
    note: Optional[str]
    created_at: str


class Specimen(TypedDict, total=False):
    id: str
    donor_id: str
    kit_id: str
    consent_record_id: str
    storage_slot_id: Optional[str]
    specimen_type: str
    collected_at: str
    initial_volume_ml: float
    residual_volume_ml: float
    committed_volume_book_ml: float
    committed_volume_physical_ml: float
    lifecycle_status: str
    viability_status: str
    created_at: str
    updated_at: str
    version: int


class Aliquot(TypedDict, total=False):
    id: str
    specimen_id: str
    storage_slot_id: Optional[str]
    initial_volume_ml: float
    remaining_volume_ml: float
    status: str
    reserved_for_request_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict, total=False):
    id: str
    unit_code: str
    setpoint_c: float
    warn_threshold_c: float
    fail_threshold_c: float
    posture: str
    peak_excursion_c: float
    cumulative_degree_minutes: float
    created_at: str
    updated_at: str
    version: int


# TemperatureReading is an immutable audit record: only id + created_at, no updated_at/version.
class TemperatureReading(TypedDict, total=False):
    id: str
    storage_unit_id: str
    recorded_at: str
    temp_c: float
    created_at: str


class StorageSlot(TypedDict, total=False):
    id: str
    storage_unit_id: str
    slot_code: str
    capacity_ml: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SlotReservation(TypedDict, total=False):
    id: str
    storage_slot_id: str
    starts_at: str
    ends_at: str
    purpose: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SampleRequest(TypedDict, total=False):
    id: str
    requester_user_id: str
    title: str
    required_uses: List[str]
    specimen_type: str
    volume_needed_ml: float
    sharing_agreement_id: str
    status: str
    revision_round: int
    votes_for: int
    votes_against: int
    charged_volume_ml: float
    fulfilled_volume_ml: float
    handling_fee_cents: int
    recall_required: bool
    created_at: str
    updated_at: str
    version: int


# ReviewVote is an immutable audit record: only id + created_at, no updated_at/version.
class ReviewVote(TypedDict, total=False):
    id: str
    sample_request_id: str
    reviewer_user_id: str
    decision: str
    rationale: str
    created_at: str


class SharingAgreement(TypedDict, total=False):
    id: str
    recipient_institution: str
    scope_uses: List[str]
    total_committed_volume_ml: float
    remaining_volume_ml: float
    reserved_volume_ml: float
    fulfilled_volume_ml: float
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeidentificationKey(TypedDict, total=False):
    id: str
    specimen_id: str
    key_code: str
    holder_user_id: str
    status: str
    reveal_count: int
    created_at: str
    updated_at: str
    version: int


class KeyAccessGrant(TypedDict, total=False):
    id: str
    deidentification_key_id: str
    grantee_user_id: str
    starts_at: str
    ends_at: str
    purpose: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DestructionOrder(TypedDict, total=False):
    id: str
    specimen_id: str
    consent_record_id: Optional[str]
    reason: str
    created_by_user_id: str
    confirmed_by_user_id: Optional[str]
    status: str
    due_at: str
    completed_late: bool
    created_at: str
    updated_at: str
    version: int
