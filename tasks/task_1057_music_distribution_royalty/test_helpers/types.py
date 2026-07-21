"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ARTIST = "Artist"
    COLLABORATOR = "Collaborator"
    DISTRIBUTION_OPS = "DistributionOps"
    FINANCE_OPS = "FinanceOps"
    FAN = "Fan"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LIVE = "LIVE"
    TAKEN_DOWN = "TAKEN_DOWN"


class ReleaseDeliveryStatus(str, Enum):
    NONE = "NONE"
    QUEUED = "QUEUED"
    PARTIAL = "PARTIAL"
    DELIVERED = "DELIVERED"
    TAKEDOWN_PENDING = "TAKEDOWN_PENDING"
    TAKEN_DOWN = "TAKEN_DOWN"


class TrackStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CollaboratorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TaxFormStatus(str, Enum):
    MISSING = "MISSING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class PayoutMethod(str, Enum):
    PAYPAL = "PAYPAL"
    BANK_TRANSFER = "BANK_TRANSFER"


class SplitSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TAKEDOWN_REQUESTED = "TAKEDOWN_REQUESTED"
    TAKEN_DOWN = "TAKEN_DOWN"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    INGESTING = "INGESTING"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class RoyaltySource(str, Enum):
    STREAMING = "STREAMING"
    DOWNLOAD = "DOWNLOAD"
    CONTENT_ID = "CONTENT_ID"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class TaxFormLifecycle(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class DeliveryAckOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# --- Entities carrying id + created_at + updated_at + version ---

class SubscriptionPlan(TypedDict):
    id: str
    code: str
    name: str
    annual_fee_cents: int
    included_release_slots: int
    commission_bps: int
    allows_content_id: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    code: str
    name: str
    supports_pre_save: bool
    requires_isrc: bool
    requires_explicit_flag: bool
    delivery_lead_days: int
    surcharge_bps: int
    max_concurrent_deliveries: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    display_name: str
    legal_name: str
    country_code: str
    email: str
    status: str
    lifetime_gross_cents: int
    live_track_count: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    artist_id: str
    plan_id: str
    status: str
    activated_at: Optional[str]
    past_due_since: Optional[str]
    releases_used: int
    auto_renew: bool
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict):
    id: str
    artist_id: str
    title: str
    upc: Optional[str]
    release_date: str
    primary_genre: str
    label_name: str
    status: str
    delivery_status: str
    rejection_reason_code: Optional[str]
    pre_save_enabled: bool
    pre_save_opens_at: Optional[str]
    pre_save_count: int
    submitted_at: Optional[str]
    taken_down_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Track(TypedDict):
    id: str
    release_id: str
    title: str
    isrc: Optional[str]
    duration_seconds: int
    track_number: int
    explicit: Optional[bool]
    content_id_enabled: bool
    status: str
    locked_split_sheet_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Collaborator(TypedDict):
    id: str
    artist_id: str
    name: str
    email: str
    country_code: str
    tax_form_status: str
    payout_method: str
    withholding_bps: int
    pending_payout_cents: int
    lifetime_paid_cents: int
    reversed_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SplitSheet(TypedDict):
    id: str
    track_id: str
    effective_from: str
    status: str
    total_share_bps: int
    accepted_share_count: int
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SplitShare(TypedDict):
    id: str
    split_sheet_id: str
    collaborator_id: str
    share_bps: int
    accepted: bool
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    release_id: str
    store_id: str
    scheduled_send_at: str
    status: str
    attempt_count: int
    last_error_code: Optional[str]
    sent_at: Optional[str]
    taken_down_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    artist_id: str
    period_start: str
    period_end: str
    status: str
    line_count: int
    gross_cents: int
    content_id_gross_cents: int
    commission_cents: int
    content_id_bonus_cents: int
    provisional_net_cents: int
    net_cents: int
    reconciled_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    collaborator_id: str
    royalty_statement_id: str
    gross_cents: int
    withholding_bps: int
    withholding_cents: int
    net_cents: int
    status: str
    auto_approved: bool
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    paid_at: Optional[str]
    reversal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxForm1099(TypedDict):
    id: str
    collaborator_id: str
    tax_year: int
    total_paid_cents: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger entry: carries ONLY id + created_at (PRD 2.4) ---

class RoyaltyLine(TypedDict):
    id: str
    royalty_statement_id: str
    track_id: str
    store_id: str
    units: int
    gross_cents: int
    source: str
    reported_at: str
    created_at: str
