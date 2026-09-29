"""Domain types for the Private Road Association Maintenance & Assessment API.

Entity TypedDicts, status enums, and the role enum. Every one of the twelve
persisted record types carries `id`, `created_at`, `updated_at`, and `version`
(PRD §2.4).
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    ASSOCIATION_SECRETARY = "AssociationSecretary"
    ASSESSMENT_CLERK = "AssessmentClerk"
    BOARD_TREASURER = "BoardTreasurer"
    ROAD_COMMISSIONER = "RoadCommissioner"
    MEMBER_OWNER = "MemberOwner"
    CONTRACTOR = "Contractor"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class VotingBasis(str, Enum):
    PER_PARCEL = "PER_PARCEL"
    ASSESSED_SHARE = "ASSESSED_SHARE"


class DelinquencyInterestBasis(str, Enum):
    STATUTORY = "STATUTORY"
    ASSOCIATION_POLICY = "ASSOCIATION_POLICY"


class ReservePosture(str, Enum):
    UNDERFUNDED = "UNDERFUNDED"
    ADEQUATE = "ADEQUATE"
    FULLY_FUNDED = "FULLY_FUNDED"


class SurfaceType(str, Enum):
    GRAVEL = "GRAVEL"
    CHIP_SEAL = "CHIP_SEAL"
    PAVED = "PAVED"


class EmergencyAccessGrade(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class UsageClass(str, Enum):
    RESIDENTIAL_YEAR_ROUND = "RESIDENTIAL_YEAR_ROUND"
    SEASONAL = "SEASONAL"
    AGRICULTURAL = "AGRICULTURAL"
    COMMERCIAL = "COMMERCIAL"
    UNDEVELOPED = "UNDEVELOPED"


class ParcelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUBDIVIDED = "SUBDIVIDED"
    PENDING_CONNECTION = "PENDING_CONNECTION"
    WITHDRAWN = "WITHDRAWN"


class MemberStandingStatus(str, Enum):
    PENDING_DEED_VERIFICATION = "PENDING_DEED_VERIFICATION"
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    LIEN_FILED = "LIEN_FILED"


class MemberAccessStatus(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    WARNED = "WARNED"
    RESTRICTED = "RESTRICTED"


class AssessmentRollStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    LEVIED = "LEVIED"


class MethodVariant(str, Enum):
    FRONTAGE_WEIGHTED = "FRONTAGE_WEIGHTED"
    TRIP_GENERATION_WEIGHTED = "TRIP_GENERATION_WEIGHTED"


class ChargeType(str, Enum):
    ANNUAL = "ANNUAL"
    SPECIAL = "SPECIAL"
    CONNECTION_FEE = "CONNECTION_FEE"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    DELINQUENT = "DELINQUENT"
    LIEN_ENCUMBERED = "LIEN_ENCUMBERED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ProjectType(str, Enum):
    GRADING = "GRADING"
    CULVERT = "CULVERT"
    PAVING = "PAVING"
    BRIDGE = "BRIDGE"


class CostAllocationMethod(str, Enum):
    FRONTAGE_WEIGHTED = "FRONTAGE_WEIGHTED"
    TRIP_GENERATION_WEIGHTED = "TRIP_GENERATION_WEIGHTED"
    EQUAL_SHARE = "EQUAL_SHARE"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    BALLOTING = "BALLOTING"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class BallotChoice(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


class BallotStatus(str, Enum):
    CAST = "CAST"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    VOIDED = "VOIDED"


class ProjectCategory(str, Enum):
    GRADING = "GRADING"
    SNOW = "SNOW"
    DUST = "DUST"
    CULVERT = "CULVERT"
    PAVING = "PAVING"
    BRIDGE = "BRIDGE"


class MaintenanceProjectStatus(str, Enum):
    BID_SOLICITATION = "BID_SOLICITATION"
    AWARDED = "AWARDED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ContractorBidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class DelinquencyActionType(str, Enum):
    NOTICE = "NOTICE"
    LIEN_FILING = "LIEN_FILING"
    ACCESS_RESTRICTION = "ACCESS_RESTRICTION"


class DelinquencyActionStatus(str, Enum):
    INITIATED = "INITIATED"
    EFFECTIVE = "EFFECTIVE"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class ConnectionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ConnectionOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISPUTED = "DISPUTED"


# --------------------------------------------------------------------------
# Entity TypedDicts — all twelve carry id/created_at/updated_at/version
# --------------------------------------------------------------------------

class Association(TypedDict):
    id: str
    name: str
    reserve_target_cents: int
    default_voting_basis: str
    delinquency_interest_basis: str
    quorum_bps: int
    reserve_balance_cents: int
    reserve_funding_ratio: float
    reserve_posture: str
    created_at: str
    updated_at: str
    version: int


class RoadSegment(TypedDict):
    id: str
    association_id: str
    name: str
    length_feet: float
    width_feet: float
    max_grade_pct: float
    surface_type: str
    turnout_count: int
    culvert_count: int
    turnaround_present: bool
    bridge_present: bool
    bridge_load_rating_tons: Optional[float]
    required_turnouts: int
    emergency_access_grade: str
    last_inspection_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    road_segment_id: str
    deed_book_page: str
    frontage_feet: float
    usage_class: str
    trips_per_day: int
    covenant_recorded: bool
    status: str
    parent_parcel_id: Optional[str]
    frontage_share_units: float
    trip_share_units: float
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    parcel_id: str
    owner_name: str
    deed_book_page: str
    deed_recorded_date: str
    standing_status: str
    access_status: str
    deed_verified_at: Optional[str]
    encumbered_principal_cents: int
    restricted_days_used: int
    created_at: str
    updated_at: str
    version: int


class AssessmentRoll(TypedDict):
    id: str
    association_id: str
    fiscal_year: int
    fy_start_date: str
    fy_end_date: str
    budget_requirement_cents: int
    method_variant: str
    status: str
    total_share_units: float
    total_levied_cents: int
    unallocated_residual_cents: int
    reserve_contribution_cents: int
    certified_at: Optional[str]
    levied_at: Optional[str]
    due_date: Optional[str]
    recall_count: int
    created_at: str
    updated_at: str
    version: int


class AssessmentCharge(TypedDict):
    id: str
    roll_id: str
    parcel_id: str
    member_id: str
    proposal_id: Optional[str]
    charge_type: str
    status: str
    share_units_snapshot: float
    amount_cents: int
    paid_cents: int
    balance_cents: int
    due_date: Optional[str]
    delinquent_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialAssessmentProposal(TypedDict):
    id: str
    road_segment_id: str
    project_type: str
    title: str
    estimated_cost_cents: int
    cost_allocation_method: str
    voting_basis: str
    status: str
    required_threshold_bps: int
    eligible_weight_total: int
    counted_weight_total: int
    yes_weight_total: int
    no_weight_total: int
    abstain_weight_total: int
    quorum_met: bool
    failed_tally_count: int
    approved_amount_cents: int
    balloting_opened_at: Optional[str]
    balloting_closes_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict):
    id: str
    proposal_id: str
    member_id: str
    choice: str
    status: str
    weight_snapshot: int
    cast_at: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceProject(TypedDict):
    id: str
    road_segment_id: str
    proposal_id: Optional[str]
    category: str
    window_start_date: str
    window_end_date: str
    status: str
    created_by_user_id: str
    awarded_bid_id: Optional[str]
    awarded_amount_cents: int
    reserve_draw_cents: int
    awarded_by_user_id: Optional[str]
    completed_at: Optional[str]
    actual_cost_cents: Optional[int]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractorBid(TypedDict):
    id: str
    project_id: str
    contractor_name: str
    contractor_user_id: str
    amount_cents: int
    bond_on_file: bool
    status: str
    submitted_at: str
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DelinquencyAction(TypedDict):
    id: str
    charge_id: str
    member_id: str
    action_type: str
    status: str
    restriction_start_date: Optional[str]
    restriction_end_date: Optional[str]
    restriction_days: int
    lien_amount_cents: int
    payoff_amount_cents: int
    initiated_by_user_id: str
    effectuated_by_user_id: Optional[str]
    effective_at: Optional[str]
    released_at: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConnectionRequest(TypedDict):
    id: str
    parcel_id: str
    requested_usage_class: str
    requested_trips_per_day: int
    easement_grant_recorded: bool
    status: str
    connection_fee_cents: int
    reserve_buyin_cents: int
    dispute_reason: Optional[str]
    resolution_note: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
