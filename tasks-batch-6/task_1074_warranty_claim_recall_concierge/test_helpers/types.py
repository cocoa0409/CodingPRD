"""Domain types: entity TypedDicts, status enums, and the role enum.

Derived from the Warranty-Claim & Recall Concierge PRD (Sections 2-4).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────
class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    ADULT = "ADULT"
    MINOR = "MINOR"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class ExposureScoringMode(str, Enum):
    WEIGHTED = "WEIGHTED"
    COUNT = "COUNT"


class ProductRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ARCHIVED = "ARCHIVED"


class ProductRecallStatus(str, Enum):
    NONE = "NONE"
    RECALLED = "RECALLED"
    REMEDIED = "REMEDIED"


class CoverageStatus(str, Enum):
    UNDER_WARRANTY = "UNDER_WARRANTY"
    EXPIRED = "EXPIRED"
    COVERED_BY_RECALL = "COVERED_BY_RECALL"


class RecallSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RemedyType(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"
    REFUND = "REFUND"


class RecallNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class RecallMatchStatus(str, Enum):
    MATCHED = "MATCHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REMEDIED = "REMEDIED"
    DISMISSED = "DISMISSED"


class ClaimType(str, Enum):
    WARRANTY = "WARRANTY"
    RECALL = "RECALL"


class ResolutionPreference(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    REFUND = "REFUND"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_DOCS = "NEEDS_DOCS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class DocType(str, Enum):
    RECEIPT = "RECEIPT"
    PHOTO = "PHOTO"
    SERIAL_PROOF = "SERIAL_PROOF"
    OTHER = "OTHER"


class ResolutionMode(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    REFUND = "REFUND"


class RefundVariant(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"


class RmaStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"


class ResolutionStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HOUSEHOLD_OWNER = "HouseholdOwner"
    HOUSEHOLD_MEMBER = "HouseholdMember"
    CONCIERGE_AGENT = "ConciergeAgent"
    MANUFACTURER_AGENT = "ManufacturerAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────
# common_fields: true entities carry id/created_at/updated_at/version.
class Household(TypedDict):
    id: str
    primary_email: str
    display_name: str
    exposure_scoring_mode: str
    recall_exposure_score: int
    active_claim_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    household_id: str
    full_name: str
    email: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    household_id: str
    tier: str
    status: str
    period_start: str
    period_end: str
    claims_used: int
    auto_renew: bool
    created_at: str
    updated_at: str
    version: int


class Manufacturer(TypedDict):
    id: str
    name: str
    contact_email: str
    coordination_enabled: bool
    rma_required: bool
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    household_id: str
    manufacturer_id: str
    model_number: str
    serial_number: int
    purchase_date: str
    purchase_price_cents: int
    warranty_months: int
    registration_status: str
    recall_status: str
    warranty_expires_at: str
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    manufacturer_id: str
    affected_model_number: str
    serial_range_start: int
    serial_range_end: int
    severity: str
    remedy_type: str
    effective_from: str
    effective_to: str
    status: str
    matched_product_count: int
    created_at: str
    updated_at: str
    version: int


class RecallMatch(TypedDict):
    id: str
    recall_notice_id: str
    product_id: str
    severity_weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    product_id: str
    filed_by_member_id: str
    recall_match_id: Optional[str]
    claim_type: str
    resolution_preference: str
    issue_description: str
    shipping_cost_cents: int
    reviewed_by_user_id: Optional[str]
    status: str
    settlement_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable append-only; NO updated_at, NO version.
class ClaimDocument(TypedDict):
    id: str
    claim_id: str
    doc_type: str
    file_uri: str
    created_at: str


class Resolution(TypedDict):
    id: str
    claim_id: str
    replacement_product_id: Optional[str]
    mode: str
    refund_variant: Optional[str]
    refund_amount_cents: Optional[int]
    shipping_cost_cents: int
    shipping_reimbursement_cents: int
    concierge_fee_cents: int
    settlement_total_cents: int
    rma_status: str
    status: str
    created_at: str
    updated_at: str
    version: int
