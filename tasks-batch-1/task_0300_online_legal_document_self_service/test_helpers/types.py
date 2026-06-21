"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions and lifecycle states. AssembledClause
is the one immutable resource (id + created_at only; no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    ATTORNEY = "Attorney"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Fixed vocabularies ───────────────────────────────
class StateCode(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    FL = "FL"


class DocumentType(str, Enum):
    WILL = "WILL"
    LLC = "LLC"
    POA = "POA"
    LEASE = "LEASE"


class Tier(str, Enum):
    FREE = "FREE"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


# ─── Status enums ─────────────────────────────────────
class SubscriptionStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class DocumentProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    ASSEMBLED = "ASSEMBLED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    FINALIZED = "FINALIZED"
    SIGNED = "SIGNED"
    STORED = "STORED"
    ABANDONED = "ABANDONED"
    STORAGE_LOCKED = "STORAGE_LOCKED"


class AttorneyReviewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CANCELLED = "CANCELLED"


class SignatureRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class DocumentRevisionStatus(str, Enum):
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class NotaryReferralStatus(str, Enum):
    REFERRED = "REFERRED"


class UpdateReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ───
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    state_of_residence: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_project_credits: int
    included_clause_count: int
    subscription_discount_pct: float
    review_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    tier: str
    status: str
    credits_used: int
    credits_remaining: int
    created_at: str
    updated_at: str
    version: int


class ClauseTemplate(TypedDict):
    id: str
    clause_key: str
    document_type: str
    state_code: str
    is_mandatory: bool
    body_text: str
    created_at: str
    updated_at: str
    version: int


class DocumentProject(TypedDict):
    id: str
    customer_id: str
    subscription_id: str
    document_type: str
    state_code: str
    title: str
    attorney_review_addon: bool
    lease_property_ref: Optional[str]
    lease_start_date: Optional[str]
    lease_end_date: Optional[str]
    status: str
    provisional_completeness: float
    assembled_completeness: float
    assembled_clause_count: int
    credit_held: bool
    created_at: str
    updated_at: str
    version: int


class QuestionnaireResponse(TypedDict):
    id: str
    document_project_id: str
    answers: dict
    answered_required_count: int
    total_required_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only frozen snapshot: id + created_at ONLY
class AssembledClause(TypedDict):
    id: str
    document_project_id: str
    source_clause_template_id: str
    clause_key: str
    is_mandatory: bool
    body_text: str
    created_at: str


class DocumentRevision(TypedDict):
    id: str
    document_project_id: str
    expected_document_project_version: int
    revision_number: int
    clause_snapshot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict):
    id: str
    full_name: str
    bar_state: str
    created_at: str
    updated_at: str
    version: int


class AttorneyReview(TypedDict):
    id: str
    document_project_id: str
    attorney_id: str
    window_start: str
    window_end: str
    status: str
    surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class SignatureRequest(TypedDict):
    id: str
    document_revision_id: str
    signer_emails: List[str]
    notary_required: bool
    signed_emails: List[str]
    signed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NotaryReferral(TypedDict):
    id: str
    signature_request_id: str
    referral_state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    document_project_id: str
    provisional_quote_cents: int
    final_invoice_cents: int
    amount_charged_cents: int
    amount_refunded_cents: int
    net_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class UpdateReminder(TypedDict):
    id: str
    document_project_id: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
