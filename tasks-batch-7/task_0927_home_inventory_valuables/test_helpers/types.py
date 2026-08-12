"""Domain types for the Home Inventory & Valuables Vault API.

Entity field sets mirror the response projections declared in PRD 2.11.
Resources that carry only `id` and `created_at` (PRD 2.4) deliberately omit
`updated_at` and `version` from their TypedDicts.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HOMEOWNER = "Homeowner"
    HOUSEHOLD_MEMBER = "HouseholdMember"
    APPRAISER = "Appraiser"
    INSURANCE_AGENT = "InsuranceAgent"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    ESTATE_EXECUTOR = "EstateExecutor"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    LIMITED = "LIMITED"
    EXECUTOR = "EXECUTOR"
    HEIR = "HEIR"


class WriteGateState(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    READ_ONLY = "READ_ONLY"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ESTATE = "ESTATE"


class SubscriptionStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    LAPSED = "LAPSED"
    CLOSED = "CLOSED"


class RefreshState(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    GRACE = "GRACE"
    OVERDUE = "OVERDUE"


class ItemCategory(str, Enum):
    JEWELRY = "JEWELRY"
    FINE_ART = "FINE_ART"
    ELECTRONICS = "ELECTRONICS"
    FURNITURE = "FURNITURE"
    APPLIANCE = "APPLIANCE"
    COLLECTIBLE = "COLLECTIBLE"
    MUSICAL_INSTRUMENT = "MUSICAL_INSTRUMENT"
    FIREARM = "FIREARM"
    WATCH = "WATCH"
    GENERAL = "GENERAL"


class ItemLifecycleState(str, Enum):
    DRAFT = "DRAFT"
    CATALOGED = "CATALOGED"
    FROZEN = "FROZEN"
    REPLACED = "REPLACED"
    DISPOSED = "DISPOSED"


class EvidenceTier(str, Enum):
    NONE = "NONE"
    PHOTO_ONLY = "PHOTO_ONLY"
    PHOTO_SERIAL = "PHOTO_SERIAL"
    DOCUMENTED = "DOCUMENTED"


class ValuationState(str, Enum):
    UNVALUED = "UNVALUED"
    DECLARED_ONLY = "DECLARED_ONLY"
    APPRAISAL_REQUIRED = "APPRAISAL_REQUIRED"
    CERTIFIED = "CERTIFIED"


class EffectiveValueBasis(str, Enum):
    NONE = "NONE"
    DECLARED = "DECLARED"
    ACV = "ACV"
    APPRAISAL = "APPRAISAL"


class CoverageMode(str, Enum):
    BLANKET = "BLANKET"
    SCHEDULED = "SCHEDULED"


class AssetKind(str, Enum):
    PHOTO = "PHOTO"
    SERIAL_PLATE = "SERIAL_PLATE"
    RECEIPT = "RECEIPT"
    PROVENANCE_DOC = "PROVENANCE_DOC"
    APPRAISAL_PDF = "APPRAISAL_PDF"


class AssetStatus(str, Enum):
    STORED = "STORED"
    DELETED = "DELETED"


class AppraiserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AppraisalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class VoidReason(str, Enum):
    APPRAISER_WITHDRAWN = "APPRAISER_WITHDRAWN"
    SCOPE_REVOKED = "SCOPE_REVOKED"
    VALUE_DISPUTED = "VALUE_DISPUTED"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPPLEMENT_REQUESTED = "SUPPLEMENT_REQUESTED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ClaimLineStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class DenialReason(str, Enum):
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    NOT_COVERED = "NOT_COVERED"
    VALUE_DISPUTED = "VALUE_DISPUTED"
    DUPLICATE = "DUPLICATE"


class Peril(str, Enum):
    FIRE = "FIRE"
    THEFT = "THEFT"
    WATER = "WATER"
    STORM = "STORM"
    OTHER = "OTHER"


class SettlementBasis(str, Enum):
    ACV = "ACV"
    RCV = "RCV"


class DeductibleMode(str, Enum):
    PRO_RATA = "PRO_RATA"
    HIGHEST_VALUE_FIRST = "HIGHEST_VALUE_FIRST"


class EstatePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"


class ValuationMode(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class Disposition(str, Enum):
    KEEP = "KEEP"
    SELL = "SELL"
    DONATE = "DONATE"
    DISCARD = "DISCARD"


class ScopeKind(str, Enum):
    HOUSEHOLD = "HOUSEHOLD"
    ROOM = "ROOM"
    PACKAGE = "PACKAGE"
    CLAIM = "CLAIM"


class RedactionLevel(str, Enum):
    VALUES_HIDDEN = "VALUES_HIDDEN"
    SERIALS_HIDDEN = "SERIALS_HIDDEN"
    FULL = "FULL"


class ShareGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    VOIDED_BY_SCOPE = "VOIDED_BY_SCOPE"


class VoidedReason(str, Enum):
    SCOPE_DELETED = "SCOPE_DELETED"
    SCOPE_SUPERSEDED = "SCOPE_SUPERSEDED"
    SUBSCRIPTION_LAPSED = "SUBSCRIPTION_LAPSED"


class CoverageGapBasis(str, Enum):
    SCHEDULED_FIRST = "SCHEDULED_FIRST"
    BLANKET_FIRST = "BLANKET_FIRST"


class BillingOutcome(str, Enum):
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    LAPSE = "LAPSE"
    CLOSE = "CLOSE"


class ProrationMode(str, Enum):
    DAILY = "DAILY"
    WHOLE_PERIOD = "WHOLE_PERIOD"


class AdjudicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# --- Entity shapes (PRD 2.11 projections) ---

class Member(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    member_role: str
    household_id: Optional[str]


class Household(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    address_label: str
    write_gate_state: str
    records_freeze_active: bool
    item_count: int
    asset_count: int
    asset_bytes_used: int
    frozen_item_count: int
    active_share_count: int
    total_effective_value_cents: int


class Subscription(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    tier: str
    status: str
    refresh_state: str
    period_start_at: str
    period_end_at: str
    past_due_since_at: Optional[str]
    last_attested_at: Optional[str]
    refresh_due_at: str
    appraisal_credits_remaining: int
    packages_used_this_period: int
    monthly_fee_cents: int
    last_proration_charge_cents: int


class Room(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    name: str
    floor_label: str
    item_count: int


class Item(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    room_id: str
    name: str
    category: str
    quantity: int
    serial_number: Optional[str]
    acquired_at: str
    purchase_price_cents: Optional[int]
    replacement_cost_cents: Optional[int]
    declared_value_cents: int
    declared_by_member_id: Optional[str]
    lifecycle_state: str
    evidence_tier: str
    valuation_state: str
    effective_value_cents: int
    effective_value_basis: str
    acv_value_cents: int
    coverage_mode: str
    scheduled_policy_id: Optional[str]
    scheduled_value_cents: int
    replaces_item_id: Optional[str]
    serial_chain_intact: bool
    allocated_quantity: int
    frozen_by_claim_id: Optional[str]


# Carries only id + created_at (PRD 2.4).
class Asset(TypedDict):
    id: str
    created_at: str
    item_id: str
    asset_kind: str
    byte_size: int
    checksum: str
    captured_at: str
    status: str


# Carries only id + created_at (PRD 2.4).
class CategorySchedule(TypedDict):
    id: str
    created_at: str
    category: str
    useful_life_months: int
    annual_depreciation_pct: float
    salvage_floor_pct: float
    blanket_sublimit_cents: int
    appraisal_scope: str
    serial_required: bool


class Appraiser(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    display_name: str
    credential_id: str
    scope_categories: List[str]
    linked_member_id: Optional[str]
    status: str


class Appraisal(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    item_id: str
    appraiser_id: str
    requested_by_member_id: str
    status: str
    inspection_start_at: str
    inspection_end_at: str
    appraised_value_cents: Optional[int]
    certified_at: Optional[str]
    valid_until_at: Optional[str]
    credit_consumed: bool
    void_reason: Optional[str]


class Policy(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    carrier_name: str
    policy_number: str
    deductible_cents: int
    scheduled_allowance_cents: int
    scheduled_consumed_cents: int
    scheduled_remaining_cents: int
    coverage_gap_cents: int
    total_effective_value_cents: int
    effective_from: str


class DocumentationPackage(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    policy_id: str
    status: str
    recipient_ref: Optional[str]
    generated_at: Optional[str]
    delivered_at: Optional[str]
    expires_at: Optional[str]
    line_count: int
    snapshot_total_effective_cents: int
    snapshot_total_covered_cents: int
    snapshot_coverage_gap_cents: int
    stale_line_count: int
    superseded_by_package_id: Optional[str]


# Carries only id + created_at (PRD 2.4).
class PackageLine(TypedDict):
    id: str
    created_at: str
    package_id: str
    item_id: str
    snapshot_name: str
    snapshot_category: str
    snapshot_evidence_tier: str
    snapshot_effective_value_cents: int
    snapshot_effective_value_basis: str
    snapshot_covered_cents: int
    snapshot_coverage_mode: str
    stale: bool


class LossClaim(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    package_id: str
    policy_id: str
    loss_date: str
    peril: str
    settlement_basis: str
    deductible_mode: str
    affected_room_ids: List[str]
    status: str
    submitted_at: Optional[str]
    frozen_item_count: int
    line_count: int
    approved_line_count: int
    denied_line_count: int
    blocked_line_count: int
    total_settlement_cents: int


class ClaimLine(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    claim_id: str
    item_id: str
    claimed_quantity: int
    status: str
    gross_value_cents: int
    capped_value_cents: int
    deductible_share_cents: int
    net_settlement_cents: int
    appeal_count: int
    settlement_hold: bool
    basis_downgraded: bool
    denial_reason: Optional[str]


class EstatePlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    executor_member_id: str
    status: str
    valuation_mode: str
    proposed_at: Optional[str]
    approved_at: Optional[str]
    executed_at: Optional[str]
    approved_by_member_id: Optional[str]
    heir_count: int
    balance_spread_pct: Optional[float]
    balanced: bool
    unallocated_item_count: int


class Allocation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    estate_plan_id: str
    item_id: str
    heir_member_id: Optional[str]
    disposition: str
    quantity: int
    allocated_value_cents: int
    blocked: bool


class ShareGrant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    scope_kind: str
    scope_room_id: Optional[str]
    scope_package_id: Optional[str]
    scope_claim_id: Optional[str]
    recipient_ref: str
    redaction_level: str
    share_token: str
    starts_at: str
    expires_at: str
    access_cap: int
    access_count: int
    status: str
    voided_reason: Optional[str]
