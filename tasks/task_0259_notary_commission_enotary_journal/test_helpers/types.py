"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the Notary Commission & E-Notary Journal contract. Monetary
quantities are integer cents (no fractional currency).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMMISSION_AUTHORITY = "CommissionAuthority"
    NOTARY = "Notary"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums (exact uppercase state strings)
# ---------------------------------------------------------------------------
class NotaryStatus(str, Enum):
    APPLIED = "APPLIED"
    COMMISSIONED = "COMMISSIONED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class BondStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class RenewalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IDENTITY_PENDING = "IDENTITY_PENDING"
    ID_VERIFIED = "ID_VERIFIED"
    ID_FAILED = "ID_FAILED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class SignerIdStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    NOTARIZED = "NOTARIZED"
    REFUSED = "REFUSED"


class JournalEntryStatus(str, Enum):
    POSTED = "POSTED"
    AMENDED = "AMENDED"
    VOID = "VOID"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"


class ActType(str, Enum):
    ACKNOWLEDGMENT = "ACKNOWLEDGMENT"
    JURAT = "JURAT"
    OATH = "OATH"
    COPY_CERTIFICATION = "COPY_CERTIFICATION"
    SIGNATURE_WITNESS = "SIGNATURE_WITNESS"


class IdMethod(str, Enum):
    PERSONAL_KNOWLEDGE = "PERSONAL_KNOWLEDGE"
    CREDIBLE_WITNESS = "CREDIBLE_WITNESS"
    ID_CREDENTIAL = "ID_CREDENTIAL"
    KBA_PLUS_CREDENTIAL = "KBA_PLUS_CREDENTIAL"


class FeeBasis(str, Enum):
    PER_ACT = "PER_ACT"
    AGGREGATE = "AGGREGATE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Primary resources carry id + created_at + updated_at + version.
# AuditEvent is append-only: id + created_at ONLY (no updated_at, no version).
# ---------------------------------------------------------------------------
class Jurisdiction(TypedDict):
    id: str
    state_code: str
    ron_allowed: bool
    bond_minimum_cents: int
    commission_term_months: int
    renewal_grace_days: int
    session_act_fee_cap_cents: int
    ron_surcharge_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    jurisdiction_id: str
    act_type: str
    max_act_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Notary(TypedDict):
    id: str
    jurisdiction_id: str
    full_name: str
    email: str
    enotary_requested: bool
    enotary_authorized: bool
    status: str
    bond_id: Optional[str]
    commission_starts_at: Optional[str]
    commission_expires_at: Optional[str]
    risk_score: int
    lifetime_fees_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    notary_id: str
    jurisdiction_id: str
    face_value_cents: int
    coverage_start_at: str
    coverage_end_at: str
    claims_paid_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Renewal(TypedDict):
    id: str
    notary_id: str
    expected_notary_version: int
    new_bond_id: str
    status: str
    filed_within_grace: bool
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    notary_id: str
    jurisdiction_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    requested_surcharge_cents: int
    fee_basis: str
    status: str
    surcharge_charged_cents: int
    act_fees_total_cents: int
    session_total_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Signer(TypedDict):
    id: str
    session_id: str
    full_name: str
    kba_passed: bool
    credential_analysis_passed: bool
    id_status: str
    created_at: str
    updated_at: str
    version: int


class Document(TypedDict):
    id: str
    session_id: str
    signer_id: str
    act_type: str
    requested_fee_cents: int
    capped_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class JournalEntry(TypedDict):
    id: str
    notary_id: str
    session_id: Optional[str]
    document_id: Optional[str]
    act_type: str
    signer_name: str
    id_method: str
    fee_charged_cents: int
    status: str
    amends_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    notary_id: str
    filed_by_user_id: str
    category: str
    claim_amount_cents: int
    status: str
    settled_claim_cents: int
    created_at: str
    updated_at: str
    version: int


# AuditEvent is append-only — id + created_at ONLY.
class AuditEvent(TypedDict):
    id: str
    notary_id: str
    entity_type: str
    entity_id: str
    action: str
    actor_role: str
    detail: str
    created_at: str
