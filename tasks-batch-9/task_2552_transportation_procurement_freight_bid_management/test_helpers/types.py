"""Domain types for the Freight Bid Management API.

Entity TypedDicts, status enumerations and the role enumeration, all derived
from the PRD's declared resource shapes and state machines.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROCUREMENT_ANALYST = "ProcurementAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CATEGORY_MANAGER = "CategoryManager"
    CONTRACT_ADMIN = "ContractAdmin"
    CARRIER_REP = "CarrierRep"


# ─── Enumerations ─────────────────────────────────────────────────────────────

class CarrierStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SCREENING = "SCREENING"
    QUALIFIED = "QUALIFIED"
    CONDITIONALLY_QUALIFIED = "CONDITIONALLY_QUALIFIED"
    WATCHLIST = "WATCHLIST"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class DiversityClassification(str, Enum):
    NONE = "NONE"
    MWBE = "MWBE"
    VETERAN_OWNED = "VETERAN_OWNED"
    SMALL_BUSINESS = "SMALL_BUSINESS"


class ServiceMode(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"


class CompositeScoreVariant(str, Enum):
    PROVISIONAL_SCREENING = "PROVISIONAL_SCREENING"
    FINAL_PERFORMANCE = "FINAL_PERFORMANCE"


class QualificationReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    REMEDIATION = "REMEDIATION"
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    REJECTED = "REJECTED"


class ArmResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class DecisionOutcome(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_CONDITIONAL = "APPROVE_CONDITIONAL"
    REMEDIATE = "REMEDIATE"
    REJECT = "REJECT"


class ScorecardStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DISPUTED = "DISPUTED"


class BidEventStatus(str, Enum):
    DRAFT = "DRAFT"
    LANES_LOCKED = "LANES_LOCKED"
    INVITING = "INVITING"
    ROUND_OPEN = "ROUND_OPEN"
    ROUND_CLOSED = "ROUND_CLOSED"
    OPTIMIZING = "OPTIMIZING"
    AWARDING = "AWARDING"
    AWARDED = "AWARDED"
    LIVE = "LIVE"


class CostBasis(str, Enum):
    FORECAST = "FORECAST"
    HISTORICAL = "HISTORICAL"


class LaneStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"
    AWARDED = "AWARDED"
    UNDER_REBID = "UNDER_REBID"


class EquipmentType(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"


class DataQualityFlag(str, Enum):
    MILEAGE_IMPLAUSIBLE = "MILEAGE_IMPLAUSIBLE"
    MISSING_TRAILING_VOLUME = "MISSING_TRAILING_VOLUME"
    VOLUME_VARIANCE_HIGH = "VOLUME_VARIANCE_HIGH"
    SEASONALITY_EXTREME = "SEASONALITY_EXTREME"
    NO_INCUMBENT_BASELINE = "NO_INCUMBENT_BASELINE"
    ACCESSORIAL_OUTLIER = "ACCESSORIAL_OUTLIER"


class InvitationStatus(str, Enum):
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class BidRoundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class IncumbentVisibility(str, Enum):
    HIDDEN = "HIDDEN"
    RANK_ONLY = "RANK_ONLY"
    FULL = "FULL"


class LaneBidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    SHORTLISTED = "SHORTLISTED"
    AWARDED_PRIMARY = "AWARDED_PRIMARY"
    AWARDED_BACKUP = "AWARDED_BACKUP"
    NOT_AWARDED = "NOT_AWARDED"


class OptimizationRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


class RoutingPosition(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP_1 = "BACKUP_1"
    BACKUP_2 = "BACKUP_2"


class AwardAllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    SUSPENDED_ROUTING = "SUSPENDED_ROUTING"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    AMENDED = "AMENDED"


class SignatureStatus(str, Enum):
    PENDING_BOTH = "PENDING_BOTH"
    PENDING_SHIPPER = "PENDING_SHIPPER"
    PENDING_CARRIER = "PENDING_CARRIER"
    FULLY_SIGNED = "FULLY_SIGNED"


class RateLoadStatus(str, Enum):
    NOT_STAGED = "NOT_STAGED"
    STAGED = "STAGED"
    LOADED = "LOADED"
    LIVE = "LIVE"


class RateRecordStatus(str, Enum):
    STAGED = "STAGED"
    LOADED = "LOADED"
    LIVE = "LIVE"
    AT_RISK = "AT_RISK"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"


class TenderOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"


class MiniBidStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OPEN = "OPEN"
    APPLIED = "APPLIED"
    DENIED = "DENIED"
    REVERTED = "REVERTED"


class MiniBidOrigin(str, Enum):
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class MiniBidTriggerReason(str, Enum):
    TENDER_REJECTION_RATE = "TENDER_REJECTION_RATE"
    MARKET_INDEX = "MARKET_INDEX"
    CAPACITY_FAILURE = "CAPACITY_FAILURE"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Thirteen resource types carry id + created_at + updated_at + version (PRD §2.6).
# TenderEvent is the exception: it carries only id and created_at.


class Carrier(TypedDict):
    id: str
    legal_name: str
    scac_code: str
    status: str
    status_reason: Optional[str]
    diversity_classification: str
    service_modes: List[str]
    fleet_power_units: int
    auto_liability_limit_usd: float
    cargo_limit_usd: float
    insurance_expiry_date: str
    capability_score: float
    composite_score: float
    composite_score_variant: str
    published_scorecard_count: int
    active_primary_lane_count: int
    committed_volume_loads: int
    qualified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualificationReview(TypedDict):
    id: str
    carrier_id: str
    status: str
    required_modes: List[str]
    min_auto_liability_usd: float
    min_cargo_usd: float
    insurance_result: str
    capability_result: str
    verified_auto_liability_usd: Optional[float]
    verified_cargo_usd: Optional[float]
    verified_expiry_date: Optional[str]
    capability_score: Optional[float]
    insurance_verified_at: Optional[str]
    capability_screened_at: Optional[str]
    decision_outcome: Optional[str]
    decision_note: Optional[str]
    decision_by_user_id: Optional[str]
    remediation_count: int
    created_at: str
    updated_at: str
    version: int


class Scorecard(TypedDict):
    id: str
    carrier_id: str
    period_start: str
    period_end: str
    on_time_pct: float
    claims_ratio: float
    tender_acceptance_pct: float
    period_tender_count: int
    composite_score: float
    status: str
    published_at: Optional[str]
    disputed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BidEvent(TypedDict):
    id: str
    name: str
    cost_basis: str
    fuel_index_per_mile: float
    accessorial_inflation_factor: float
    rate_floor_per_mile: float
    rounds_allowed: int
    current_round_no: int
    cost_weight: float
    service_weight: float
    capacity_weight: float
    diversity_weight: float
    diversity_min_pct: float
    max_award_share_pct: float
    max_carriers_per_lane: int
    contract_effective_from: str
    contract_effective_to: str
    status: str
    lane_count: int
    invited_carrier_count: int
    accepted_invitation_count: int
    total_scope_volume_loads: int
    baseline_cost_usd: Optional[float]
    award_cost_usd: Optional[float]
    savings_pct: Optional[float]
    coverage_pct: float
    diversity_pct: float
    awarded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict):
    id: str
    bid_event_id: str
    lane_code: str
    origin_zip3: str
    dest_zip3: str
    equipment_type: str
    mileage: int
    annual_volume_loads: int
    trailing_12m_actual_loads: Optional[int]
    seasonality_peak_index: float
    accessorial_history_usd_per_load: float
    incumbent_carrier_id: Optional[str]
    incumbent_rate_per_mile: Optional[float]
    service_days_required: int
    status: str
    data_quality_flags: List[str]
    unallocated_volume_loads: int
    awarded_coverage_pct: float
    baseline_cost_usd: Optional[float]
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invitation(TypedDict):
    id: str
    bid_event_id: str
    carrier_id: str
    status: str
    nda_required: bool
    nda_signed: bool
    qualification_snapshot_score: float
    qualification_snapshot_carrier_version: int
    snapshot_stale: bool
    decline_reason: Optional[str]
    responded_at: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BidRound(TypedDict):
    id: str
    bid_event_id: str
    round_no: int
    status: str
    incumbent_visibility: str
    target_reduction_pct: float
    opens_at: str
    closes_at: str
    submitted_bid_count: int
    lowest_rate_per_mile: Optional[float]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaneBid(TypedDict):
    id: str
    bid_round_id: str
    lane_id: str
    carrier_id: str
    rate_per_mile: float
    fuel_surcharge_included: bool
    committed_volume_loads: int
    transit_days_offered: int
    status: str
    is_incumbent: bool
    evaluated_basis: str
    effective_rate_per_mile: float
    awardable_volume_loads: int
    linehaul_per_load_usd: float
    accessorial_per_load_usd: float
    cost_per_load_usd: float
    evaluated_total_cost_usd: float
    service_credit_pct: float
    cost_rank_score: float
    rank_in_lane: int
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OptimizationRun(TypedDict):
    id: str
    bid_event_id: str
    scenario_label: str
    max_carriers_per_lane: int
    diversity_min_pct: float
    min_capacity_coverage_pct: float
    status: str
    total_cost_usd: float
    coverage_pct: float
    diversity_pct: float
    objective_score: float
    infeasible_lane_ids: List[str]
    proposed_primary_count: int
    proposed_backup_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AwardAllocation(TypedDict):
    id: str
    bid_event_id: str
    optimization_run_id: str
    lane_id: str
    carrier_id: str
    lane_bid_id: str
    routing_position: str
    allocated_volume_loads: int
    allocated_pct: float
    allocated_cost_usd: float
    status: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    promoted_from_position: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    bid_event_id: str
    carrier_id: str
    status: str
    signature_status: str
    rate_load_status: str
    effective_from: str
    effective_to: str
    carrier_signed_by_user_id: Optional[str]
    carrier_signed_at: Optional[str]
    shipper_signed_by_user_id: Optional[str]
    shipper_signed_at: Optional[str]
    base_committed_value_usd: float
    volume_discount_pct: float
    volume_discount_usd: float
    accessorial_allowance_pct: float
    accessorial_allowance_usd: float
    total_committed_value_usd: float
    amendment_count: int
    rate_record_count: int
    created_at: str
    updated_at: str
    version: int


class RateRecord(TypedDict):
    id: str
    contract_id: str
    lane_id: str
    carrier_id: str
    award_allocation_id: str
    superseded_by_rate_record_id: Optional[str]
    routing_position: str
    rate_per_mile: float
    fuel_surcharge_included: bool
    effective_from: str
    effective_to: str
    committed_volume_loads: int
    committed_value_usd: float
    status: str
    tender_count: int
    rejection_count: int
    rejection_pct: float
    acceptance_pct: float
    loaded_at: Optional[str]
    live_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MiniBid(TypedDict):
    id: str
    bid_event_id: str
    lane_id: str
    rate_record_id: str
    applied_rate_record_id: Optional[str]
    proposed_by_carrier_id: Optional[str]
    trigger_reason: str
    origin: str
    status: str
    window_open_at: str
    window_close_at: str
    proposed_rate_per_mile: Optional[float]
    adjustment_pct: Optional[float]
    contract_value_before_usd: Optional[float]
    contract_value_after_usd: Optional[float]
    denial_reason: Optional[str]
    revert_reason: Optional[str]
    applied_at: Optional[str]
    reverted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TenderEvent(TypedDict):
    """A tender outcome is an immutable append to a log: it carries only
    ``id`` and ``created_at`` — no ``updated_at`` and no ``version`` (PRD §2.6).
    """

    id: str
    rate_record_id: str
    outcome: str
    load_reference: str
    reject_reason: Optional[str]
    position_used: str
    tendered_at: str
    created_at: str
