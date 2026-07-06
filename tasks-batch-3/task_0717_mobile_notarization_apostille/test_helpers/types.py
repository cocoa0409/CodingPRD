"""Domain types: entity TypedDicts, status enums, role enum.

All structures here mirror the resource shapes the PRD describes. Entities that
the PRD declares immutable (FeeSchedule, JournalEntry, RetentionRecord) carry only
``id`` and ``created_at`` — no ``updated_at`` and no ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class NotaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class SigningRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ASSIGNED = "ASSIGNED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    ENDED = "ENDED"


class RecordingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RECORDING = "RECORDING"
    ARCHIVED = "ARCHIVED"


class TrustVariant(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class VerificationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EntryStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ApostilleStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ROUTED = "ROUTED"
    AUTHENTICATED = "AUTHENTICATED"
    RETURNED = "RETURNED"
    REJECTED = "REJECTED"


class AuthenticationType(str, Enum):
    APOSTILLE = "APOSTILLE"
    CERTIFICATION = "CERTIFICATION"


class LoanPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SCRUBBED = "SCRUBBED"
    FUNDED = "FUNDED"
    CANCELLED = "CANCELLED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PURGEABLE = "PURGEABLE"


class DocCategory(str, Enum):
    GENERAL = "GENERAL"
    REAL_ESTATE = "REAL_ESTATE"
    LOAN_SIGNING = "LOAN_SIGNING"
    APOSTILLE_BOUND = "APOSTILLE_BOUND"


class DeliveryMode(str, Enum):
    RON = "RON"
    MOBILE = "MOBILE"


class IdDocType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    PASSPORT = "PASSPORT"
    STATE_ID = "STATE_ID"


class DocType(str, Enum):
    DEED = "DEED"
    MORTGAGE = "MORTGAGE"
    POA = "POA"
    AFFIDAVIT = "AFFIDAVIT"
    BIRTH_CERT = "BIRTH_CERT"
    DIPLOMA = "DIPLOMA"
    OTHER = "OTHER"


class ActType(str, Enum):
    ACKNOWLEDGMENT = "ACKNOWLEDGMENT"
    JURAT = "JURAT"
    OATH = "OATH"
    COPY_CERTIFICATION = "COPY_CERTIFICATION"


class UserRole(str, Enum):
    CoordinatorOps = "CoordinatorOps"
    Notary = "Notary"
    ApostilleClerk = "ApostilleClerk"
    Viewer = "Viewer"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────

# Immutable config — id + created_at only (no updated_at, no version).
class FeeSchedule(TypedDict):
    id: str
    state_code: str
    per_stamp_cents: int
    travel_base_cents: int
    travel_per_mile_cents: int
    ron_surcharge_cents: int
    state_cap_cents: int
    enhanced_trust_required: bool
    created_at: str


class Account(TypedDict):
    id: str
    org_name: str
    default_state_code: str
    retention_years: int
    created_at: str
    updated_at: str
    version: int


class Notary(TypedDict):
    id: str
    account_id: str
    full_name: str
    commission_state: str
    commission_expires_at: str
    ron_authorized: bool
    nsa_certified: bool
    status: str
    active_session_count: int
    created_at: str
    updated_at: str
    version: int


class Signer(TypedDict):
    id: str
    account_id: str
    full_name: str
    email: str
    id_doc_type: str
    created_at: str
    updated_at: str
    version: int


class SigningRequest(TypedDict):
    id: str
    account_id: str
    signer_id: str
    state_code: str
    doc_category: str
    delivery_mode: str
    expected_stamp_count: int
    estimated_travel_miles: int
    assigned_notary_id: Optional[str]
    status: str
    estimate_fee_cents: int
    final_fee_cents: int
    actual_travel_miles: int
    created_at: str
    updated_at: str
    version: int


class RequestDocument(TypedDict):
    id: str
    request_id: str
    title: str
    doc_type: str
    requires_apostille: bool
    signing_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    request_id: str
    notary_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RonSession(TypedDict):
    id: str
    request_id: str
    notary_id: str
    scheduled_start: str
    scheduled_end: str
    session_status: str
    recording_status: str
    created_at: str
    updated_at: str
    version: int


class IdVerification(TypedDict):
    id: str
    request_id: str
    signer_id: str
    kba_score: int
    credential_score: int
    biometric_score: int
    trust_variant: str
    trust_score: float
    outcome: str
    created_at: str
    updated_at: str
    version: int


# Immutable append-only — id + created_at only (no updated_at, no version).
class JournalEntry(TypedDict):
    id: str
    request_id: str
    document_id: str
    notary_id: str
    act_type: str
    entry_status: str
    created_at: str


class ApostilleOrder(TypedDict):
    id: str
    document_id: str
    destination_country: str
    authentication_type: str
    sos_office_state: str
    fee_cents: int
    status: str
    resubmit_count: int
    created_at: str
    updated_at: str
    version: int


class LoanPackage(TypedDict):
    id: str
    request_id: str
    lender_ref: str
    package_discount_pct: float
    scrub_passed: bool
    package_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable append-only retention ledger — id + created_at only.
class RetentionRecord(TypedDict):
    id: str
    request_id: str
    journal_entry_count: int
    retain_until: str
    hold_status: str
    created_at: str
