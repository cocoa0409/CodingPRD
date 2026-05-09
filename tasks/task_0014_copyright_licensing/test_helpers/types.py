"""Domain types for the Copyright Licensing API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --- Role enum (PRD §2.1) ---

class UserRole(str, Enum):
    RIGHTS_HOLDER = "RightsHolder"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Work fields (PRD §3.1, §3.2) ---

class WorkType(str, Enum):
    LITERARY = "LITERARY"
    MUSIC = "MUSIC"
    FILM = "FILM"
    SOFTWARE = "SOFTWARE"
    ARTWORK = "ARTWORK"


class WorkRegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"


# --- RightsHolder fields (PRD §3.1) ---

class HolderType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ENTITY = "ENTITY"


# --- License fields (PRD §3.3, §3.6) ---

class LicenseStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SIGNED = "SIGNED"
    EFFECTIVE = "EFFECTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class LicenseExclusivity(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class LicenseRevisionRights(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    FULL = "FULL"


class LicenseSettlementPeriod(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class LicenseMediaType(str, Enum):
    DIGITAL = "DIGITAL"
    PRINT = "PRINT"
    BROADCAST = "BROADCAST"
    MERCHANDISE = "MERCHANDISE"


# --- NegotiationRound fields (PRD §3.3) ---

class NegotiationAction(str, Enum):
    OFFER = "OFFER"
    COUNTER = "COUNTER"
    ACCEPT = "ACCEPT"
    WITHDRAW = "WITHDRAW"


# --- Contract fields (PRD §3.5, §3.6) ---

class ContractStatus(str, Enum):
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    FULLY_SIGNED = "FULLY_SIGNED"
    EFFECTIVE = "EFFECTIVE"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"


# --- RoyaltyStatement fields (PRD §3.7) ---

class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class RoyaltyStatementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# --- InfringementCase fields (PRD §3.8) ---

class InfringementReviewStage(str, Enum):
    REPORTED = "REPORTED"
    OWNERSHIP_VERIFIED = "OWNERSHIP_VERIFIED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    UNDER_ARBITRATION = "UNDER_ARBITRATION"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


# --- RightsChainEvent / AuditLog change types (PRD §3.2, §3.9) ---

class RightsChainEventType(str, Enum):
    REGISTERED = "REGISTERED"
    LICENSE_SIGNED = "LICENSE_SIGNED"
    LICENSE_TERMINATED = "LICENSE_TERMINATED"
    INFRINGEMENT_RESOLVED = "INFRINGEMENT_RESOLVED"
    OWNERSHIP_TRANSFERRED = "OWNERSHIP_TRANSFERRED"


class AuditChangeType(str, Enum):
    LICENSE_CHANGED = "LICENSE_CHANGED"
    CONTRACT_AMENDED = "CONTRACT_AMENDED"
    DISPUTE_LOGGED = "DISPUTE_LOGGED"
    ROYALTY_REVERSED = "ROYALTY_REVERSED"
    RIGHTS_CONFLICT_DETECTED = "RIGHTS_CONFLICT_DETECTED"


# --- ExternalEvent enums (PRD §2.11) ---

class ExternalSource(str, Enum):
    PAYMENT = "PAYMENT"
    E_SIGN = "E_SIGN"
    COPYRIGHT_AUTHORITY = "COPYRIGHT_AUTHORITY"
    DISTRIBUTION_PLATFORM = "DISTRIBUTION_PLATFORM"


class ExternalEventType(str, Enum):
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    PAYMENT_REFUNDED = "PAYMENT_REFUNDED"
    SIGNATURE_VERIFIED = "SIGNATURE_VERIFIED"
    SIGNATURE_REJECTED = "SIGNATURE_REJECTED"
    REGISTRATION_APPROVED = "REGISTRATION_APPROVED"
    REGISTRATION_REJECTED = "REGISTRATION_REJECTED"
    TAKEDOWN_ACKED = "TAKEDOWN_ACKED"
    DISTRIBUTION_REVENUE_REPORTED = "DISTRIBUTION_REVENUE_REPORTED"


# --- Top-level entity TypedDicts (common_fields=true: id + created_at + updated_at + version) ---

class RightsHolder(TypedDict, total=False):
    id: str
    legal_name: str
    holder_type: str
    contact_email: str
    jurisdiction: str
    created_at: str
    updated_at: str
    version: int


class CoOwnerEntry(TypedDict, total=False):
    rights_holder_id: str
    share_bps: int


class Work(TypedDict, total=False):
    id: str
    title: str
    work_type: str
    creation_date: str
    primary_owner_id: str
    co_owners: List[CoOwnerEntry]
    primary_share_bps: int
    ownership_proof_doc_id: str
    registration_status: str
    certificate_id: Optional[str]
    certificate_issued_at: Optional[str]
    rights_chain_event_count: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    work_id: str
    licensor_id: str
    licensee_id: str
    territory: List[str]
    term_start: str
    term_end: str
    media_types: List[str]
    exclusivity: str
    sublicense_allowed: bool
    revision_rights: str
    fixed_fee_cents: int
    revenue_share_bps: int
    minimum_guarantee_cents: int
    advance_cents: int
    settlement_period: str
    status: str
    current_round: int
    pinned_work_version: Optional[int]
    contract_id: Optional[str]
    effective_date: Optional[str]
    cumulative_advance_recouped_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    license_id: str
    signing_order: List[str]
    effective_date_target: str
    status: str
    signed_count: int
    fully_signed_at: Optional[str]
    parent_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    license_id: str
    period_start_at: str
    period_end_at: str
    gross_revenue_cents: int
    variant: str
    earned_royalty_cents: int
    advance_recouped_cents: int
    net_payable_cents: int
    status: str
    settled_at: Optional[str]
    reversal_of_id: Optional[str]
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InfringementCase(TypedDict, total=False):
    id: str
    work_id: str
    reporter_id: str
    alleged_infringer_id: str
    evidence_doc_ids: List[str]
    response_text: Optional[str]
    review_stage: str
    takedown_issued_at: Optional[str]
    compensation_cents: Optional[int]
    pinned_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only sub-resource TypedDicts (common_fields=false: id + created_at only) ---

class NegotiationRound(TypedDict, total=False):
    id: str
    license_id: str
    round_number: int
    proposed_by_id: str
    clause_diff: dict
    action: str
    submitted_at: str
    created_at: str


class Signature(TypedDict, total=False):
    id: str
    contract_id: str
    signer_id: str
    signature_payload: str
    signed_at: str
    created_at: str


class RightsChainEvent(TypedDict, total=False):
    id: str
    work_id: str
    event_type: str
    actor_id: str
    ref_entity: str
    ref_id: str
    payload: dict
    created_at: str


class ExternalEvent(TypedDict, total=False):
    id: str
    source: str
    event_type: str
    ref_entity: str
    ref_id: str
    payload: dict
    external_event_id: str
    applied: bool
    applied_at: Optional[str]
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_id: str
    subject_entity: str
    subject_id: str
    change_type: str
    before: Optional[Any]
    after: Optional[Any]
    created_at: str
