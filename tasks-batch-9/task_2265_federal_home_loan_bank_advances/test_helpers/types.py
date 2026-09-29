"""Domain types for the FHLB Advances Collateral Pledging API.

Status enums, role enum and entity TypedDicts. Field names are exactly as the
PRD declares them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    CREDIT_OFFICER = "CreditOfficer"
    TREASURY_OFFICER = "TreasuryOfficer"
    COLLATERAL_CUSTODIAN = "CollateralCustodian"
    COLLATERAL_REVIEW_AUDITOR = "CollateralReviewAuditor"
    COMMUNITY_LENDING_MANAGER = "CommunityLendingManager"


# ---------------------------------------------------------------------------
# MemberBank
# ---------------------------------------------------------------------------

class CharterType(str, Enum):
    COMMERCIAL_BANK = "COMMERCIAL_BANK"
    THRIFT = "THRIFT"
    CREDIT_UNION = "CREDIT_UNION"
    INSURANCE_COMPANY = "INSURANCE_COMPANY"
    CDFI = "CDFI"


class MembershipStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PledgeMode(str, Enum):
    NONE = "NONE"
    BLANKET_LIEN = "BLANKET_LIEN"
    SPECIFIC_LISTING = "SPECIFIC_LISTING"
    DELIVERY_REQUIRED = "DELIVERY_REQUIRED"


class PledgeAgreementStatus(str, Enum):
    NONE = "NONE"
    EXECUTED = "EXECUTED"


class CollateralPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ShortfallStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class LatestReviewOutcome(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    QUALIFIED = "QUALIFIED"
    FAIL = "FAIL"


class MemberBank(TypedDict, total=False):
    id: str
    name: str
    charter_type: str
    total_assets_cents: int
    credit_rating_tier: int
    cdfi_certified: bool
    membership_status: str
    pledge_mode: str
    pledge_agreement_status: str
    pledge_agreement_effective_date: Optional[str]
    collateral_posture: str
    shortfall_status: str
    shortfall_required_cure_cents: int
    shortfall_opened_at: Optional[str]
    shortfall_cure_deadline: Optional[str]
    verification_haircut_bps: int
    latest_review_outcome: str
    required_membership_stock_cents: int
    required_activity_stock_cents: int
    required_total_stock_cents: int
    stock_held_cents: int
    stock_deficiency_cents: int
    excess_stock_cents: int
    lendable_collateral_value_cents: int
    total_outstanding_advances_cents: int
    committed_advances_cents: int
    borrowing_capacity_cents: int
    community_lending_eligible: bool
    delivery_required: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# StockSubscription
# ---------------------------------------------------------------------------

class SubscriptionType(str, Enum):
    MEMBERSHIP = "MEMBERSHIP"
    ACTIVITY = "ACTIVITY"


class StockSubscriptionStatus(str, Enum):
    SUBSCRIBED = "SUBSCRIBED"
    ISSUED = "ISSUED"
    REDEMPTION_REQUESTED = "REDEMPTION_REQUESTED"
    REPURCHASED = "REPURCHASED"
    CANCELLED = "CANCELLED"


class StockSubscription(TypedDict, total=False):
    id: str
    member_bank_id: str
    subscription_type: str
    amount_cents: int
    shares: int
    status: str
    advance_id: Optional[str]
    redemption_requested_at: Optional[str]
    repurchased_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# CollateralAsset
# ---------------------------------------------------------------------------

class AssetClass(str, Enum):
    SF_MORTGAGE = "SF_MORTGAGE"
    MULTIFAMILY = "MULTIFAMILY"
    CRE = "CRE"
    HELOC = "HELOC"
    SMALL_BUSINESS = "SMALL_BUSINESS"
    CDFI_COMMUNITY = "CDFI_COMMUNITY"
    AGENCY_MBS = "AGENCY_MBS"
    TREASURY = "TREASURY"


class CollateralAssetStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    SUSPENDED = "SUSPENDED"
    SUBSTITUTED = "SUBSTITUTED"


class IneligibilityReason(str, Enum):
    NONE = "NONE"
    DOCUMENTATION_MISSING = "DOCUMENTATION_MISSING"
    LTV_EXCEEDS_MAX = "LTV_EXCEEDS_MAX"
    DELINQUENT = "DELINQUENT"
    SECURITIES_NOT_DELIVERED = "SECURITIES_NOT_DELIVERED"
    UNRESOLVED_REVIEW_FINDING = "UNRESOLVED_REVIEW_FINDING"


class DocumentationStatus(str, Enum):
    COMPLETE = "COMPLETE"
    EXCEPTION = "EXCEPTION"
    MISSING = "MISSING"


class CustodyLocation(str, Enum):
    MEMBER_VAULT = "MEMBER_VAULT"
    THIRD_PARTY_CUSTODIAN = "THIRD_PARTY_CUSTODIAN"
    FHLB_SAFEKEEPING = "FHLB_SAFEKEEPING"


class EffectiveListingMode(str, Enum):
    BLANKET = "BLANKET"
    SPECIFIC = "SPECIFIC"
    DELIVERED = "DELIVERED"


class CollateralAsset(TypedDict, total=False):
    id: str
    member_bank_id: str
    asset_class: str
    unpaid_principal_balance_cents: int
    market_value_cents: int
    ltv_bps: int
    delinquency_days: int
    documentation_status: str
    custody_location: str
    appraisal_date: str
    status: str
    ineligibility_reason: str
    collateral_basis_cents: int
    effective_listing_mode: str
    discount_factor_bps: int
    lendable_value_cents: int
    replaces_asset_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# SafekeepingReceipt
# ---------------------------------------------------------------------------

class SafekeepingReceiptStatus(str, Enum):
    PENDING_DELIVERY = "PENDING_DELIVERY"
    RECEIVED = "RECEIVED"
    EXCEPTION = "EXCEPTION"
    RETURNED = "RETURNED"


class SafekeepingConfirmOutcome(str, Enum):
    RECEIVED = "RECEIVED"
    EXCEPTION = "EXCEPTION"


class SafekeepingReceipt(TypedDict, total=False):
    id: str
    collateral_asset_id: str
    member_bank_id: str
    file_count: int
    delivery_date: str
    return_date: str
    status: str
    received_at: Optional[str]
    exception_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# CollateralVerificationReview / ReviewFinding
# ---------------------------------------------------------------------------

class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIELD_WORK = "FIELD_WORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"


class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    QUALIFIED = "QUALIFIED"
    FAIL = "FAIL"


class CollateralVerificationReview(TypedDict, total=False):
    id: str
    member_bank_id: str
    window_start: str
    window_end: str
    sample_size: int
    status: str
    retest_count: int
    outcome: str
    haircut_bps: int
    weighted_exception_score: float
    exception_rate_pct: float
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FindingType(str, Enum):
    MISSING_NOTE = "MISSING_NOTE"
    LIEN_DEFECT = "LIEN_DEFECT"
    STALE_APPRAISAL = "STALE_APPRAISAL"
    UNREPORTED_DELINQUENCY = "UNREPORTED_DELINQUENCY"
    INELIGIBLE_PROPERTY_TYPE = "INELIGIBLE_PROPERTY_TYPE"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATED = "REMEDIATED"
    WAIVED = "WAIVED"
    UNRESOLVED = "UNRESOLVED"


class ReviewFinding(TypedDict, total=False):
    id: str
    collateral_verification_review_id: str
    collateral_asset_id: str
    finding_type: str
    severity: str
    weight: float
    status: str
    raised_by_user_id: str
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# AdvanceProduct / Advance
# ---------------------------------------------------------------------------

class ProductStructure(str, Enum):
    FIXED_TERM = "FIXED_TERM"
    ADJUSTABLE = "ADJUSTABLE"
    AMORTIZING = "AMORTIZING"
    CALLABLE = "CALLABLE"
    PUTABLE = "PUTABLE"


class PrepaymentFeeMethod(str, Enum):
    SYMMETRIC_MARKET_VALUE = "SYMMETRIC_MARKET_VALUE"
    YIELD_MAINTENANCE = "YIELD_MAINTENANCE"
    FLAT_PCT = "FLAT_PCT"
    NONE = "NONE"


class AdvanceProduct(TypedDict, total=False):
    id: str
    product_code: str
    structure: str
    min_term_days: int
    max_term_days: int
    rate_bps: int
    prepayment_fee_method: str
    activity_stock_pct_bps: int
    min_principal_cents: int
    flat_prepayment_fee_bps: int
    symmetric_credit_enabled: bool
    requires_collateral_delivery: bool
    community_program_flag: bool
    created_at: str
    updated_at: str
    version: int


class AdvanceCreditStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CREDIT_APPROVED = "CREDIT_APPROVED"
    FUNDED = "FUNDED"
    REPAID = "REPAID"
    PREPAID = "PREPAID"
    CANCELLED_FOR_COLLATERAL = "CANCELLED_FOR_COLLATERAL"


class AdvanceCollateralStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    SECURED = "SECURED"
    SHORTFALL = "SHORTFALL"
    RELEASED = "RELEASED"


class CommunityBucket(str, Enum):
    NONE = "NONE"
    FIRST_TIME_HOMEBUYER = "FIRST_TIME_HOMEBUYER"
    REHABILITATION = "REHABILITATION"
    GENERAL = "GENERAL"


class Advance(TypedDict, total=False):
    id: str
    member_bank_id: str
    advance_product_id: str
    term_days: int
    requested_net_proceeds_cents: int
    gross_principal_cents: int
    net_proceeds_cents: int
    activity_stock_cents: int
    rate_bps: int
    fund_stock_from_advance: bool
    credit_status: str
    collateral_status: str
    outstanding_principal_cents: int
    approved_by_user_id: Optional[str]
    funded_by_user_id: Optional[str]
    funded_at: Optional[str]
    maturity_date: Optional[str]
    capacity_at_request_cents: int
    capacity_at_funding_cents: Optional[int]
    community_program_allocation_id: Optional[str]
    community_bucket: str
    requested_subsidy_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# PrepaymentEvent
# ---------------------------------------------------------------------------

class PrepayKind(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class PrepaymentEventStatus(str, Enum):
    QUOTED = "QUOTED"
    SETTLED = "SETTLED"
    EXPIRED = "EXPIRED"


class PrepaymentEvent(TypedDict, total=False):
    id: str
    advance_id: str
    prepay_kind: str
    prepay_amount_cents: int
    status: str
    quote_date: str
    quoted_market_rate_bps: int
    quoted_remaining_days: int
    quoted_fee_cents: int
    settlement_date: Optional[str]
    settlement_market_rate_bps: Optional[int]
    settled_remaining_days: Optional[int]
    settled_fee_cents: Optional[int]
    admin_fee_cents: int
    symmetric_credit_cents: int
    fee_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# CommunityProgramAllocation
# ---------------------------------------------------------------------------

class ProgramCode(str, Enum):
    CIP = "CIP"
    AHP_SETASIDE = "AHP_SETASIDE"
    CICA = "CICA"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CommunityProgramAllocation(TypedDict, total=False):
    id: str
    program_code: str
    fiscal_year: int
    total_pool_cents: int
    subsidy_rate_bps: int
    bucket_capacity_first_time_cents: int
    bucket_capacity_rehabilitation_cents: int
    bucket_capacity_general_cents: int
    bucket_committed_first_time_cents: int
    bucket_committed_rehabilitation_cents: int
    bucket_committed_general_cents: int
    committed_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Capacity read
# ---------------------------------------------------------------------------

class CapacityVariant(str, Enum):
    CERTIFIED = "CERTIFIED"
    PROVISIONAL = "PROVISIONAL"


class BorrowingCapacityBreakdown(TypedDict, total=False):
    variant: str
    lendable_collateral_value_cents: int
    tier_cap_bps: int
    statutory_cap_cents: int
    capacity_base_cents: int
    outstanding_advances_cents: int
    commitments_cents: int
    borrowing_capacity_cents: int


ALL_ENTITY_NAMES: List[str] = [
    "MemberBank",
    "StockSubscription",
    "CollateralAsset",
    "SafekeepingReceipt",
    "CollateralVerificationReview",
    "ReviewFinding",
    "AdvanceProduct",
    "Advance",
    "PrepaymentEvent",
    "CommunityProgramAllocation",
]
