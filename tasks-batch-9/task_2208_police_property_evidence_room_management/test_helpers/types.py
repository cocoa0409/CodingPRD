"""Domain types for the Police Evidence Room API.

Enum members mirror the literal string values the PRD names for each field, and
the TypedDicts mirror the response bodies described in PRD sections 2.4, 3.1-3.8.
Only ChainEvent omits ``updated_at`` and ``version``: PRD section 2.4 states that a
ChainEvent "is an immutable ledger line and carries only id and created_at".
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD section 2.1) ─────────────────────────────────────────────────

class UserRole(str, Enum):
    PROPERTY_ROOM_MANAGER = "PropertyRoomManager"
    EVIDENCE_TECHNICIAN = "EvidenceTechnician"
    INVESTIGATOR = "Investigator"
    LAB_ANALYST = "LabAnalyst"
    COURT_CLERK = "CourtClerk"
    INTERNAL_AUDITOR = "InternalAuditor"


class CustodianRoleType(str, Enum):
    EVIDENCE_TECH = "EVIDENCE_TECH"
    INVESTIGATOR = "INVESTIGATOR"
    LAB_ANALYST = "LAB_ANALYST"
    AUDITOR = "AUDITOR"


class CustodianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ─── Room posture (PRD section 2.6) ──────────────────────────────────────────

class RoomPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    LOCKED_DOWN = "LOCKED_DOWN"


# ─── Statutes and storage (PRD section 3.1) ──────────────────────────────────

class PreservationClass(str, Enum):
    STANDARD = "STANDARD"
    DRUG_SCHEDULE = "DRUG_SCHEDULE"
    BIOLOGICAL_INDEFINITE = "BIOLOGICAL_INDEFINITE"
    HOMICIDE_PERMANENT = "HOMICIDE_PERMANENT"


class StorageCategory(str, Enum):
    GENERAL = "GENERAL"
    REFRIGERATED = "REFRIGERATED"
    HIGH_VALUE_VAULT = "HIGH_VALUE_VAULT"
    OVERSIZED_YARD = "OVERSIZED_YARD"


class StorageLocationStatus(str, Enum):
    OPEN = "OPEN"
    SEALED_FOR_AUDIT = "SEALED_FOR_AUDIT"


# ─── Cases and items (PRD sections 3.1, 3.2, 3.4) ────────────────────────────

class CaseStatus(str, Enum):
    OPEN = "OPEN"
    CHARGED = "CHARGED"
    ADJUDICATED = "ADJUDICATED"
    APPEAL_PENDING = "APPEAL_PENDING"
    CLOSED = "CLOSED"


class ItemCategory(str, Enum):
    GENERAL = "GENERAL"
    BIOLOGICAL = "BIOLOGICAL"
    CURRENCY = "CURRENCY"
    FIREARM = "FIREARM"
    NARCOTICS = "NARCOTICS"
    OVERSIZED = "OVERSIZED"


class PackagingType(str, Enum):
    SEALED_ENVELOPE = "SEALED_ENVELOPE"
    PAPER_BAG = "PAPER_BAG"
    RIGID_BOX = "RIGID_BOX"
    SHARPS_TUBE = "SHARPS_TUBE"
    PALLET_WRAP = "PALLET_WRAP"
    CHAIN_TAG_ONLY = "CHAIN_TAG_ONLY"


class CustodyState(str, Enum):
    LOGGED = "LOGGED"
    STORED = "STORED"
    CHECKED_OUT = "CHECKED_OUT"
    MISSING = "MISSING"
    PURGED = "PURGED"


class DispositionState(str, Enum):
    RETAINED = "RETAINED"
    DISPOSAL_ELIGIBLE = "DISPOSAL_ELIGIBLE"
    UNCLAIMED_ELIGIBLE = "UNCLAIMED_ELIGIBLE"
    COURT_HOLD = "COURT_HOLD"
    ORDER_PENDING = "ORDER_PENDING"
    DISPOSED = "DISPOSED"


class RetentionBasis(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    INDEFINITE = "INDEFINITE"
    COURT_HOLD = "COURT_HOLD"


# ─── Custody transfers (PRD section 3.5) ─────────────────────────────────────

class TransferPurpose(str, Enum):
    LAB_ANALYSIS = "LAB_ANALYSIS"
    COURT_PRESENTATION = "COURT_PRESENTATION"
    INVESTIGATIVE_REVIEW = "INVESTIGATIVE_REVIEW"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RELEASED = "RELEASED"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    DENIED = "DENIED"
    LOST = "LOST"


# ─── Owner claims (PRD section 3.6) ──────────────────────────────────────────

class NoticeMethod(str, Enum):
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    PUBLICATION = "PUBLICATION"
    IN_PERSON = "IN_PERSON"


class ClaimStatus(str, Enum):
    NOTICE_SENT = "NOTICE_SENT"
    CLAIM_FILED = "CLAIM_FILED"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


# ─── Dispositions (PRD section 3.7) ──────────────────────────────────────────

class DispositionType(str, Enum):
    RETURN_TO_OWNER = "RETURN_TO_OWNER"
    AUCTION = "AUCTION"
    DESTRUCTION = "DESTRUCTION"
    CONVERSION = "CONVERSION"


class OrderStatus(str, Enum):
    PENDING_COURT_AUTH = "PENDING_COURT_AUTH"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    DISBURSED = "DISBURSED"


class SettlementStatus(str, Enum):
    NONE = "NONE"
    HELD = "HELD"
    DISBURSED = "DISBURSED"


# ─── Audits and discrepancies (PRD section 3.8) ──────────────────────────────

class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class DiscrepancyKind(str, Enum):
    MISSING = "MISSING"
    MISPLACED = "MISPLACED"


class DiscrepancyStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED_FOUND = "RESOLVED_FOUND"
    RESOLVED_WRITTEN_OFF = "RESOLVED_WRITTEN_OFF"


class DiscrepancyResolution(str, Enum):
    FOUND = "FOUND"
    WRITTEN_OFF = "WRITTEN_OFF"


class ChainEventType(str, Enum):
    INTAKE = "INTAKE"
    STORAGE_ASSIGN = "STORAGE_ASSIGN"
    RELEASE = "RELEASE"
    RECEIPT = "RECEIPT"
    AUDIT_SCAN = "AUDIT_SCAN"
    DISCREPANCY_RAISED = "DISCREPANCY_RAISED"
    RETENTION_SET = "RETENTION_SET"
    NOTICE_SENT = "NOTICE_SENT"
    DISPOSITION_EXECUTED = "DISPOSITION_EXECUTED"


# ─── Response shapes ─────────────────────────────────────────────────────────

class PropertyRoom(TypedDict):
    id: str
    name: str
    agency_code: str
    posture: str
    open_discrepancy_count: int
    missing_high_risk_count: int
    sealed_location_count: int
    disposal_eligible_count: int
    escrow_balance_cents: int
    last_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OffenseStatute(TypedDict):
    id: str
    offense_code: str
    description: str
    preservation_class: str
    statutory_retention_days: int
    appeal_window_days: int
    destruction_requires_court_order: bool
    created_at: str
    updated_at: str
    version: int


class StorageLocation(TypedDict):
    id: str
    property_room_id: str
    code: str
    category: str
    capacity_slots: int
    temperature_c: Optional[float]
    requires_dual_signature: bool
    occupied_slots: int
    status: str
    sealed_by_audit_session_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Custodian(TypedDict):
    id: str
    property_room_id: str
    badge_number: str
    full_name: str
    role_type: str
    certification_expires_at: str
    status: str
    suspension_reason: Optional[str]
    open_escort_count: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    property_room_id: str
    offense_statute_id: str
    case_number: str
    status: str
    charged_at: Optional[str]
    adjudicated_at: Optional[str]
    appeal_opened_at: Optional[str]
    closed_at: Optional[str]
    item_count: int
    undisposed_item_count: int
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    id: str
    case_id: str
    item_description: str
    category: str
    packaging_type: str
    appraised_value_cents: int
    is_found_property: bool
    seized_at: str
    item_sequence: int
    barcode: str
    intake_at: str
    storage_location_id: Optional[str]
    required_storage_category: str
    custody_state: str
    disposition_state: str
    current_holder_id: Optional[str]
    retention_release_at: Optional[str]
    retention_basis: str
    open_transfer_count: int
    created_at: str
    updated_at: str
    version: int


class RetentionDetermination(TypedDict):
    id: str
    evidence_item_id: str
    basis: str
    resolved_basis: str
    anchor_at: Optional[str]
    statute_days_applied: int
    computed_release_at: Optional[str]
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class CustodyTransfer(TypedDict):
    id: str
    evidence_item_id: str
    from_custodian_id: Optional[str]
    to_custodian_id: str
    purpose: str
    status: str
    released_at: str
    due_back_at: str
    released_signature: Optional[str]
    witness_signature: Optional[str]
    receipt_signature: Optional[str]
    returned_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispositionOrder(TypedDict):
    id: str
    evidence_item_id: str
    type: str
    requested_by_custodian_id: str
    owner_claim_id: Optional[str]
    reserve_price_cents: Optional[int]
    status: str
    auto_authorized: bool
    court_order_number: Optional[str]
    gross_sale_cents: Optional[int]
    estimated_net_proceeds_cents: int
    commission_cents: Optional[int]
    storage_recovery_cents: Optional[int]
    settled_net_proceeds_cents: Optional[int]
    settlement_status: str
    settlement_deadline_at: Optional[str]
    executed_by_custodian_id: Optional[str]
    witness_custodian_id: Optional[str]
    authorized_at: Optional[str]
    executed_at: Optional[str]
    settled_at: Optional[str]
    payee_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OwnerClaim(TypedDict):
    id: str
    evidence_item_id: str
    claimant_name: str
    claimant_contact: str
    notice_method: str
    status: str
    notified_at: str
    claim_deadline_at: str
    proof_document_ref: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditSession(TypedDict):
    id: str
    storage_location_id: str
    auditor_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    started_at: Optional[str]
    reconciled_at: Optional[str]
    closed_at: Optional[str]
    expected_evidence_item_ids: List[str]
    expected_item_count: int
    scanned_evidence_item_ids: List[str]
    scanned_item_count: int
    missing_count: int
    misplaced_count: int
    risk_index: float
    created_at: str
    updated_at: str
    version: int


class Discrepancy(TypedDict):
    id: str
    evidence_item_id: str
    audit_session_id: Optional[str]
    kind: str
    status: str
    weight_contribution: float
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChainEvent(TypedDict):
    """PRD section 2.4: a ChainEvent carries only ``id`` and ``created_at`` — it has
    neither ``updated_at`` nor ``version``."""

    id: str
    evidence_item_id: str
    actor_custodian_id: Optional[str]
    event_type: str
    sequence_no: int
    occurred_at: str
    actor_role: str
    signature_ref: Optional[str]
    detail: str
    created_at: str
