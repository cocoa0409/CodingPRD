"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §2.9, §2.1)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TALENT_MANAGER = "TalentManager"
    BRAND_MANAGER = "BrandManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_ADMIN = "FinanceAdmin"
    CREATOR = "Creator"
    BRAND = "Brand"


class CreatorStatus(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class BrandStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BriefStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class PitchStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CREATOR = "PENDING_CREATOR"
    PENDING_BRAND = "PENDING_BRAND"
    ACTIVE = "ACTIVE"
    IN_DISPUTE = "IN_DISPUTE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class DeliverableStatus(str, Enum):
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class DisclosureCheckStatus(str, Enum):
    QUEUED = "QUEUED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class PerformanceReportStatus(str, Enum):
    REPORTED = "REPORTED"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class PayoutStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAYABLE = "PAYABLE"
    HELD = "HELD"
    PAID = "PAID"
    VOIDED = "VOIDED"
    CLAWED_BACK = "CLAWED_BACK"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DISMISSED = "RESOLVED_DISMISSED"


class ReshootStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class Niche(str, Enum):
    BEAUTY = "BEAUTY"
    FASHION = "FASHION"
    TECH = "TECH"
    FINANCE = "FINANCE"
    GAMING = "GAMING"
    FITNESS = "FITNESS"
    FOOD = "FOOD"
    TRAVEL = "TRAVEL"
    OTHER = "OTHER"


class Platform(str, Enum):
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"
    TIKTOK = "TIKTOK"
    TWITCH = "TWITCH"


class Industry(str, Enum):
    CPG = "CPG"
    TECH = "TECH"
    FINANCE = "FINANCE"
    FASHION = "FASHION"
    AUTOMOTIVE = "AUTOMOTIVE"
    GAMING = "GAMING"
    OTHER = "OTHER"


class ExclusivityCategory(str, Enum):
    NONE = "NONE"
    BEVERAGES = "BEVERAGES"
    SNACKS = "SNACKS"
    SKINCARE = "SKINCARE"
    SOFTWARE = "SOFTWARE"
    FINTECH = "FINTECH"
    AUTOMOTIVE = "AUTOMOTIVE"
    GAMING = "GAMING"
    APPAREL = "APPAREL"


class DisputeReason(str, Enum):
    RESHOOT_REQUEST = "RESHOOT_REQUEST"
    NON_PAYMENT = "NON_PAYMENT"
    DISCLOSURE_VIOLATION = "DISCLOSURE_VIOLATION"
    SCOPE_CREEP = "SCOPE_CREEP"
    OTHER = "OTHER"


class DisputeRemedy(str, Enum):
    NONE = "NONE"
    RESHOOT = "RESHOOT"
    FEE_REDUCTION = "FEE_REDUCTION"
    TERMINATE = "TERMINATE"


# All twelve resources carry the common system-managed properties of PRD §2.4
# (id, created_at, updated_at, version), so every TypedDict below includes them.


class Creator(TypedDict):
    id: str
    handle: str
    email: str
    niche: str
    primary_platform: str
    followers: int
    avg_views_30d: int
    engagement_rate_bps: int
    status: str
    rate_card_cpm_cents: int
    rate_card_flat_cents: int
    compliance_strikes: int
    lifetime_billed_cents: int
    pending_disclosure_count: int
    created_at: str
    updated_at: str
    version: int


class Brand(TypedDict):
    id: str
    name: str
    industry: str
    status: str
    credit_hold: bool
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Brief(TypedDict):
    id: str
    brand_id: str
    title: str
    niche: str
    min_followers: int
    min_engagement_bps: int
    slots_total: int
    slots_committed: int
    budget_cents: int
    deliverables_per_slot: int
    usage_rights_days: int
    exclusivity_category: str
    exclusivity_days: int
    whitelisting_required: bool
    revision_rounds_included: int
    submission_window_start: str
    submission_window_end: str
    content_window_start: str
    content_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pitch(TypedDict):
    id: str
    brief_id: str
    creator_id: str
    proposed_fee_cents: int
    concept_note: str
    status: str
    negotiation_rounds: int
    superseded_by_pitch_id: Optional[str]
    deal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    pitch_id: str
    brief_id: str
    creator_id: str
    brand_id: str
    status: str
    negotiation_rounds: int
    fee_base_cents: int
    fee_total_cents: Optional[int]
    usage_rights_days: int
    exclusivity_category: str
    exclusivity_days: int
    whitelisting: bool
    revision_rounds_included: int
    terms_version: int
    exclusive_window_start: Optional[str]
    exclusive_window_end: Optional[str]
    activated_at: Optional[str]
    reduction_pct: float
    bonus_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    deal_id: str
    platform: str
    due_date: str
    scheduled_publish_date: str
    content_url: Optional[str]
    published_at: Optional[str]
    status: str
    revision_rounds_used: int
    reshoot_count: int
    reviewed_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureCheck(TypedDict):
    id: str
    deliverable_id: str
    status: str
    recheck_count: int
    has_ad_hashtag: bool
    verbal_disclosure: bool
    platform_tool_used: bool
    checked_by_user_id: Optional[str]
    checked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReport(TypedDict):
    id: str
    deal_id: str
    period_start: str
    period_end: str
    views: int
    likes: int
    comments: int
    shares: int
    audited_views: Optional[int]
    audited_engagements: Optional[int]
    status: str
    provisional_bonus_cents: int
    final_bonus_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    deal_id: str
    brand_id: str
    status: str
    fee_line_cents: int
    service_line_cents: int
    bonus_line_cents: int
    total_cents: int
    late_fee_cents: int
    issued_at: Optional[str]
    due_date: Optional[str]
    paid_at: Optional[str]
    issued_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    invoice_id: str
    deal_id: str
    creator_id: str
    status: str
    gross_cents: int
    commission_rate_bps: int
    commission_cents: int
    net_cents: int
    payout_due_at: Optional[str]
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    deal_id: str
    deliverable_id: Optional[str]
    raised_by_role: str
    reason: str
    note: str
    status: str
    remedy: Optional[str]
    reduction_pct: Optional[float]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reshoot(TypedDict):
    id: str
    deliverable_id: str
    dispute_id: Optional[str]
    reason: str
    status: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
