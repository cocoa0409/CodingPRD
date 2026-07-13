"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the Digital-Legacy Planning API contract. Every entity carries
the common fields id/created_at/updated_at/version (all ten entity types are
versioned resources per the PRD).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    OWNER = "Owner"
    DEPUTY = "Deputy"
    PLATFORM_ADMIN = "PlatformAdmin"


class PlanLifeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INCAPACITATED = "INCAPACITATED"
    DECEASED = "DECEASED"


class VaultItemStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    RELEASED = "RELEASED"
    ARCHIVED = "ARCHIVED"


class VaultItemKind(str, Enum):
    ACCOUNT = "ACCOUNT"
    ASSET = "ASSET"
    DOCUMENT = "DOCUMENT"


class DeputyStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"


class BeneficiaryStatus(str, Enum):
    NOMINATED = "NOMINATED"
    VESTED = "VESTED"
    REMOVED = "REMOVED"


class DirectiveStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVISION = "UNDER_REVISION"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class ReleaseRequestStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class SubscriptionStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"


class SubscriptionTier(str, Enum):
    FREE = "FREE"
    PLUS = "PLUS"
    FAMILY = "FAMILY"


class ShareStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class IntegrationSyncStatus(str, Enum):
    LINKED = "LINKED"
    SYNCING = "SYNCING"


class ReviewReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"


class Plan(TypedDict, total=False):
    id: str
    owner_full_name: str
    owner_email: str
    life_status: str
    life_evidence_ref: Optional[str]
    completeness_pct: int
    seats_used: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class VaultItem(TypedDict, total=False):
    id: str
    plan_id: str
    kind: str
    category: str
    title: str
    secret_ref: str
    sensitivity: str
    gross_value_cents: Optional[int]
    liability_cents: int
    distribution_basis: str
    net_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deputy(TypedDict, total=False):
    id: str
    plan_id: str
    full_name: str
    email: str
    deputy_role: str
    access_scope: List[str]
    release_trigger: str
    authority_start_at: str
    authority_end_at: str
    consumes_seat: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    plan_id: str
    parent_beneficiary_id: Optional[str]
    asset_vault_item_id: Optional[str]
    full_name: str
    relationship: str
    contact_email: Optional[str]
    allocation_pct: float
    allocated_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Directive(TypedDict, total=False):
    id: str
    plan_id: str
    directive_type: str
    content: str
    version_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseRequest(TypedDict, total=False):
    id: str
    plan_id: str
    requested_by_deputy_id: str
    trigger_type: str
    scope_kinds: List[str]
    required_approvals: int
    approval_count: int
    approver_deputy_ids: List[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    plan_id: str
    tier: str
    refund_policy: str
    seat_limit: int
    monthly_fee_cents: int
    period_start: str
    period_end: str
    last_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Share(TypedDict, total=False):
    id: str
    plan_id: str
    vault_item_id: Optional[str]
    shared_with_email: str
    scope: str
    effective_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Integration(TypedDict, total=False):
    id: str
    plan_id: str
    provider_type: str
    provider_name: str
    external_ref: str
    coverage_cents: int
    last_synced_at: Optional[str]
    sync_status: str
    created_at: str
    updated_at: str
    version: int


class ReviewReminder(TypedDict, total=False):
    id: str
    plan_id: str
    subject_kind: str
    interval_days: int
    last_reviewed_at: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
