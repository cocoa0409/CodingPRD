"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PRICING_ANALYST = "PricingAnalyst"
    PRICING_COMMITTEE = "PricingCommittee"
    TREASURY_OFFICER = "TreasuryOfficer"
    BRANCH_BANKER = "BranchBanker"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CHANNEL_OPERATOR = "ChannelOperator"
    OPERATIONS_ADMIN = "OperationsAdmin"


class ProductClass(str, Enum):
    SAVINGS = "SAVINGS"
    MONEY_MARKET = "MONEY_MARKET"
    CD = "CD"
    INTEREST_CHECKING = "INTEREST_CHECKING"


class TierApplication(str, Enum):
    MARGINAL = "MARGINAL"
    WHOLE_BALANCE = "WHOLE_BALANCE"


class Channel(str, Enum):
    BRANCH = "BRANCH"
    ONLINE = "ONLINE"
    MOBILE = "MOBILE"
    CALL_CENTER = "CALL_CENTER"


class RateSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ScanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ANALYZED = "ANALYZED"
    ACTIONED = "ACTIONED"


class CycleStatus(str, Enum):
    CURRENT = "CURRENT"
    OVERDUE = "OVERDUE"


class PromoStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class RolloverTreatment(str, Enum):
    ROLL_TO_SHEET = "ROLL_TO_SHEET"
    RENEW_THEN_SHEET = "RENEW_THEN_SHEET"


class ExceptionStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    REBASE_REQUIRED = "REBASE_REQUIRED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AuthorityTier(str, Enum):
    BRANCH = "BRANCH"
    COMMITTEE = "COMMITTEE"


class AccountLifecycle(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class RateSource(str, Enum):
    SHEET = "SHEET"
    PROMO = "PROMO"
    EXCEPTION = "EXCEPTION"
    GRANDFATHERED = "GRANDFATHERED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class NoticeType(str, Enum):
    PRE_CHANGE = "PRE_CHANGE"
    RATE_CHANGE_ADVERSE = "RATE_CHANGE_ADVERSE"
    PROMO_EXPIRY = "PROMO_EXPIRY"


class NoticeStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    WAIVED = "WAIVED"


class DeploymentStatus(str, Enum):
    PENDING = "PENDING"
    DEPLOYED = "DEPLOYED"
    FAILED = "FAILED"
    RETIRED = "RETIRED"


class MigrationStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class TierRow(TypedDict):
    tier_index: int
    lower_bound_cents: int
    upper_bound_cents: int  # -1 = unbounded final tier
    rate_bp: int
    projected_balance_cents: int


class DepositProduct(TypedDict):
    id: str
    product_code: str
    product_class: str
    term_months: int
    tier_application: str
    rate_cap_bp: int
    allows_promos: bool
    allows_exceptions: bool
    created_at: str
    updated_at: str
    version: int


class RateSheet(TypedDict):
    id: str
    product_id: str
    market_code: str
    sheet_version: int
    effective_date: str
    end_date: str
    disclosure_lead_days: int
    margin_floor_bp: int
    source_scan_id: Optional[str]
    supersedes_sheet_id: Optional[str]
    tiers: List[TierRow]
    total_projected_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScanEntry(TypedDict):
    competitor_name: str
    product_class: str
    rate_bp: int
    tier_balance_cents: int


class CompetitorRateScan(TypedDict):
    id: str
    market_code: str
    scan_date: str
    source_name: str
    entries: List[ScanEntry]
    benchmark_weighted_bp: Optional[int]
    benchmark_simple_bp: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepricingCycle(TypedDict):
    id: str
    product_id: str
    market_code: str
    cadence_days: int
    last_reviewed_at: Optional[str]
    next_review_due: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PromotionalOffer(TypedDict):
    id: str
    product_id: str
    market_code: str
    promo_rate_bp: int
    promo_term_days: int
    enrollment_start: str
    enrollment_end: str
    min_opening_balance_cents: int
    rollover_treatment: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExceptionPricingRequest(TypedDict):
    id: str
    account_id: str
    sheet_id: str
    requested_rate_bp: int
    baseline_rate_bp: int
    delta_bp: int
    authority_tier: str
    term_days: int
    justification_doc_ref: Optional[str]
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DepositAccount(TypedDict):
    id: str
    customer_ref: str
    product_id: str
    market_code: str
    sheet_id: str
    balance_cents: int
    channel: str
    lifecycle: str
    rate_source: str
    promo_offer_id: Optional[str]
    promo_end_date: Optional[str]
    exception_request_id: Optional[str]
    exception_end_date: Optional[str]
    base_rate_bp: int
    bundle_bonus_bp: int
    exception_rate_bp: Optional[int]
    current_rate_bp: int
    unposted_accrual_milli: int
    posted_interest_cents: int
    last_accrual_date: str
    opened_at: str
    created_at: str
    updated_at: str
    version: int


class FundingCurvePoint(TypedDict):
    tenor_months: int
    cost_bp: int


class FundingCurve(TypedDict):
    id: str
    curve_date: str
    points: List[FundingCurvePoint]
    created_at: str
    updated_at: str
    version: int


class RelationshipBundle(TypedDict):
    id: str
    bundle_code: str
    bonus_bp: int
    min_combined_balance_cents: int
    required_product_classes: List[str]
    eligible_product_classes: List[str]
    created_at: str
    updated_at: str
    version: int


class CustomerBundleEnrollment(TypedDict):
    id: str
    bundle_id: str
    customer_ref: str
    qualifying_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureNotice(TypedDict):
    id: str
    sheet_id: str
    account_id: Optional[str]
    channel: str
    notice_type: str
    required_by_date: str
    sent_at: Optional[str]
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RateDeployment(TypedDict):
    id: str
    sheet_id: str
    channel: str
    deployed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MigrationBatch(TypedDict):
    id: str
    source_sheet_id: str
    target_sheet_id: str
    migrated_count: int
    skipped_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
