"""Domain types for the Residential Earthquake Coverage & Mitigation Incentive
Program API: entity TypedDicts, status enums and the role enum.

Every name here follows the field vocabulary of the PRD exactly.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PARTICIPATING_INSURER = "ParticipatingInsurer"
    POLICYHOLDER = "Policyholder"
    GRANT_REVIEWER = "GrantReviewer"
    FIELD_INSPECTOR = "FieldInspector"
    CLAIM_ADJUSTER = "ClaimAdjuster"
    CERTIFIED_CONTRACTOR = "CertifiedContractor"


# ─── Status enums ─────────────────────────────────────────────────────────────

class PolicyholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class InsurerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class InsurerComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    UNDER_REVIEW = "UNDER_REVIEW"
    SANCTIONED = "SANCTIONED"


class CountyHazardTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class SoilClass(str, Enum):
    ROCK = "ROCK"
    STIFF = "STIFF"
    SOFT = "SOFT"
    LIQUEFACTION = "LIQUEFACTION"


class StructureType(str, Enum):
    WOOD_FRAME_SLAB = "WOOD_FRAME_SLAB"
    WOOD_FRAME_CRIPPLE_WALL = "WOOD_FRAME_CRIPPLE_WALL"
    MASONRY_URM = "MASONRY_URM"
    MOBILE_HOME = "MOBILE_HOME"


class RetrofitStatus(str, Enum):
    NONE = "NONE"
    SELF_DECLARED = "SELF_DECLARED"
    VERIFIED = "VERIFIED"


class RetrofitScope(str, Enum):
    NONE = "NONE"
    CRIPPLE_WALL_BRACING = "CRIPPLE_WALL_BRACING"
    EARTHQUAKE_BRACING_SYSTEM = "EARTHQUAKE_BRACING_SYSTEM"
    ANCHOR_BOLT_ONLY = "ANCHOR_BOLT_ONLY"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class PolicyLifecycleStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    QUOTE_EXPIRED = "QUOTE_EXPIRED"


class PolicyMitigationStatus(str, Enum):
    UNMITIGATED = "UNMITIGATED"
    RETROFIT_PENDING = "RETROFIT_PENDING"
    RETROFIT_VERIFIED = "RETROFIT_VERIFIED"
    DISCOUNT_APPLIED = "DISCOUNT_APPLIED"


class RatingVariant(str, Enum):
    QUOTE_TIME = "QUOTE_TIME"
    RENEWAL_TIME = "RENEWAL_TIME"


class ProgramTrack(str, Enum):
    BRACE_AND_BOLT = "BRACE_AND_BOLT"
    MOBILE_HOME = "MOBILE_HOME"
    SOFT_STORY = "SOFT_STORY"


class GrantCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class IncomeTier(str, Enum):
    TIER_LOW = "TIER_LOW"
    TIER_MID = "TIER_MID"
    TIER_ANY = "TIER_ANY"


class FundedFromBucket(str, Enum):
    NONE = "NONE"
    TIER_LOW = "TIER_LOW"
    TIER_MID = "TIER_MID"
    TIER_ANY = "TIER_ANY"


class GrantStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    FUNDS_RESERVED = "FUNDS_RESERVED"
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CertificationStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ProjectStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_INSPECTION = "AWAITING_INSPECTION"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    VERIFIED = "VERIFIED"
    ABANDONED = "ABANDONED"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"


class EventStatus(str, Enum):
    MONITORING = "MONITORING"
    DECLARED = "DECLARED"
    LOSS_AGGREGATION = "LOSS_AGGREGATION"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    ASSESSMENT_LEVIED = "ASSESSMENT_LEVIED"
    CLOSED = "CLOSED"


class LayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class ClaimAdjustmentStatus(str, Enum):
    FNOL_RECEIVED = "FNOL_RECEIVED"
    PROVISIONAL_ADJUSTED = "PROVISIONAL_ADJUSTED"
    FINAL_ADJUSTED = "FINAL_ADJUSTED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class ClaimPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────
# Every entity below carries id, created_at, updated_at and version, EXCEPT
# AssessmentAllocation, which the PRD declares as the one immutable ledger row
# that carries only id and created_at.

class Policyholder(TypedDict):
    id: str
    full_name: str
    email: str
    county_code: str
    outreach_campaign_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ParticipatingInsurer(TypedDict):
    id: str
    name: str
    naic_code: str
    market_share_pct: float
    status: str
    compliance_status: str
    offers_recorded_count: int
    undocumented_decline_count: int
    last_take_up_rate_bp: int
    assessment_balance_cents: int
    policies_bound_count: int
    created_at: str
    updated_at: str
    version: int


class Dwelling(TypedDict):
    id: str
    policyholder_id: str
    street_address: str
    county_hazard_tier: str
    soil_class: str
    structure_type: str
    year_built: int
    dwelling_limit_cents: int
    retrofit_status: str
    verified_retrofit_scope: str
    grant_lifetime_count: int
    created_at: str
    updated_at: str
    version: int


class MandatoryOffer(TypedDict):
    id: str
    insurer_id: str
    policyholder_id: str
    dwelling_id: str
    offered_at: str
    expires_at: str
    status: str
    decline_documented: bool
    offer_round: int
    campaign_code: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    dwelling_id: str
    insurer_id: str
    policyholder_id: str
    accepted_offer_id: str
    deductible_pct: int
    contents_sublimit_cents: int
    loss_of_use_sublimit_cents: int
    rated_dwelling_limit_cents: Optional[int]
    base_premium_cents: int
    rating_variant: str
    mitigation_discount_cents: int
    annual_premium_cents: int
    prorated_credit_cents: int
    lifecycle_status: str
    mitigation_status: str
    quote_expires_at: str
    effective_at: Optional[str]
    expires_at: Optional[str]
    term_number: int
    created_at: str
    updated_at: str
    version: int


class GrantCycle(TypedDict):
    id: str
    program_track: str
    label: str
    opens_at: str
    closes_at: str
    total_pool_cents: int
    reserved_cents: int
    disbursed_cents: int
    uncommitted_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetrofitGrant(TypedDict):
    id: str
    dwelling_id: str
    policy_id: Optional[str]
    grant_cycle_id: str
    income_tier: str
    project_cost_estimate_cents: int
    requested_scope: str
    approved_amount_cents: int
    funded_from_bucket: str
    status: str
    review_round: int
    approved_by_user_id: Optional[str]
    reserved_by_user_id: Optional[str]
    denial_reason: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    business_name: str
    license_no: str
    certified_scopes: List[str]
    certification_status: str
    certification_expires_at: str
    open_project_count: int
    failed_inspection_count: int
    created_at: str
    updated_at: str
    version: int


class RetrofitProject(TypedDict):
    id: str
    grant_id: str
    contractor_id: str
    scope_code: str
    status: str
    inspection_attempts: int
    started_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    project_id: str
    contractor_id: str
    window_start: str
    window_end: str
    result: str
    inspector_user_id: Optional[str]
    recorded_at: Optional[str]
    deficiency_note: str
    created_at: str
    updated_at: str
    version: int


class CatastropheEvent(TypedDict):
    id: str
    event_code: str
    magnitude: float
    epicenter_county_code: str
    occurred_at: str
    treaty_year: int
    retention_cents: int
    status: str
    aggregate_incurred_cents: int
    retained_cents: int
    ceded_total_cents: int
    uncovered_cents: int
    assessment_shortfall_cents: int
    admin_loading_cents: int
    assessment_total_cents: int
    claim_count: int
    created_at: str
    updated_at: str
    version: int


class ReinsuranceLayer(TypedDict):
    id: str
    treaty_year: int
    layer_index: int
    attachment_point_cents: int
    limit_cents: int
    ceded_pct: float
    status: str
    ceded_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    event_id: str
    structural_damage_cents: int
    cosmetic_damage_cents: int
    contents_damage_cents: int
    loss_of_use_cents: int
    deductible_applied_cents: int
    dwelling_part_cents: int
    contents_part_cents: int
    loss_of_use_part_cents: int
    provisional_payable_cents: int
    final_payable_cents: int
    payable_cents: int
    paid_cents: int
    adjustment_status: str
    payment_status: str
    provisional_adjuster_user_id: Optional[str]
    final_adjuster_user_id: Optional[str]
    reopen_count: int
    denial_reason: str
    created_at: str
    updated_at: str
    version: int


class AssessmentAllocation(TypedDict):
    """The one ledger row that carries neither updated_at nor version."""
    id: str
    event_id: str
    insurer_id: str
    market_share_pct_snapshot: float
    assessed_cents: int
    allocation_rank: int
    absorbs_remainder: bool
    created_at: str
