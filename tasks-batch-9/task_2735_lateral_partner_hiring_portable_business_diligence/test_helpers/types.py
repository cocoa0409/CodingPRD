"""Domain types for the Lateral Partner Hiring API.

Status enums, role enum and entity TypedDicts, named exactly as the PRD names
them. Note that a CollectionRecord is an append-only observation carrying only
``id`` and ``created_at`` — its TypedDict deliberately omits ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    RECRUITING_COORDINATOR = "RecruitingCoordinator"
    CONFLICTS_COUNSEL = "ConflictsCounsel"
    COMMITTEE_CHAIR = "CommitteeChair"
    COMMITTEE_MEMBER = "CommitteeMember"
    PRACTICE_GROUP_LEADER = "PracticeGroupLeader"
    CANDIDATE = "Candidate"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------


class PracticeGroupStatus(str, Enum):
    OPEN = "OPEN"
    HIRING_FROZEN = "HIRING_FROZEN"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class FeeStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    FEE_DUE = "FEE_DUE"
    FEE_WAIVED = "FEE_WAIVED"


class FeeBasis(str, Enum):
    NONE = "NONE"
    DIRECT_PLACEMENT = "DIRECT_PLACEMENT"
    TAIL_OFF_CLAIM = "TAIL_OFF_CLAIM"


class PipelineStatus(str, Enum):
    SOURCED = "SOURCED"
    APPROACHED = "APPROACHED"
    DILIGENCE = "DILIGENCE"
    OFFER_OUT = "OFFER_OUT"
    HIRED = "HIRED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ClearanceStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class QuestionnaireStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    ABANDONED = "ABANDONED"


class ClientBookEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class PortableStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    VALIDATED = "VALIDATED"
    DECLINED = "DECLINED"


class RelationshipRole(str, Enum):
    BILLING_ATTORNEY = "BILLING_ATTORNEY"
    RELATIONSHIP_PARTNER = "RELATIONSHIP_PARTNER"
    SERVICE_PARTNER = "SERVICE_PARTNER"


class ClientConsentStatus(str, Enum):
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_CONFIRMED = "CONSENT_CONFIRMED"


class RecordType(str, Enum):
    HISTORICAL = "HISTORICAL"
    POST_HIRE = "POST_HIRE"


class CollectionRecordStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class CollectionSource(str, Enum):
    PRIOR_FIRM_STATEMENT = "PRIOR_FIRM_STATEMENT"
    CANDIDATE_ATTESTATION = "CANDIDATE_ATTESTATION"
    FIRM_LEDGER = "FIRM_LEDGER"


class AssessmentStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class GoverningBasis(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    VALIDATED = "VALIDATED"


class ConcentrationGrade(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ConflictCheckStatus(str, Enum):
    PENDING = "PENDING"
    WAIVER_PENDING = "WAIVER_PENDING"
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class ConflictSeverity(str, Enum):
    DIRECT_ADVERSE = "DIRECT_ADVERSE"
    POSITIONAL = "POSITIONAL"
    IMPUTED = "IMPUTED"


class WaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    REFUSED = "REFUSED"
    EXPIRED = "EXPIRED"


class WaiverStrategy(str, Enum):
    ADVANCE_CONSENT = "ADVANCE_CONSENT"
    ETHICAL_WALL = "ETHICAL_WALL"
    MATTER_CARVE_OUT = "MATTER_CARVE_OUT"


class DeclinationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class OfferStatus(str, Enum):
    DRAFTED = "DRAFTED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COUNTER_REQUESTED = "COUNTER_REQUESTED"
    REPRICE_REQUIRED = "REPRICE_REQUIRED"
    ACCEPTED = "ACCEPTED"
    LAPSED = "LAPSED"


class VoteDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class VoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class IntegrationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class IntroductionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VarianceBasis(str, Enum):
    PLAN_BASIS = "PLAN_BASIS"
    RATE_ADJUSTED_BASIS = "RATE_ADJUSTED_BASIS"


class PerformanceFlag(str, Enum):
    ON_PLAN = "ON_PLAN"
    WATCH = "WATCH"
    BELOW_PLAN = "BELOW_PLAN"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------


class PracticeGroup(TypedDict):
    id: str
    name: str
    status: str
    guarantee_budget_total_usd: float
    available_guarantee_budget_usd: float
    reserved_guarantee_budget_usd: float
    committed_guarantee_total_usd: float
    onboarding_capacity: int
    active_onboarding_count: int
    leverage_ratio: float
    target_standard_rate_usd: float
    created_at: str
    updated_at: str
    version: int


class SearchFirm(TypedDict):
    id: str
    name: str
    max_fee_pct: float
    max_concurrent_engagements: int
    engagement_count: int
    created_at: str
    updated_at: str
    version: int


class SearchFirmEngagement(TypedDict):
    id: str
    search_firm_id: str
    practice_group_id: str
    status: str
    fee_pct: float
    fee_cap_usd: float
    exclusivity_start_date: str
    exclusivity_end_date: str
    tail_off_days: int
    fee_status: str
    fee_basis: str
    fee_amount_usd: float
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    full_name: str
    prior_firm_name: str
    target_practice_group_id: str
    sourcing_engagement_id: str
    sponsor_user_id: str
    current_standard_rate_usd: float
    notice_period_days: int
    non_solicit_days: int
    approach_confidential: bool
    pipeline_status: str
    clearance_status: str
    resignation_date: Optional[str]
    earliest_start_date: Optional[str]
    hire_date: Optional[str]
    open_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LateralQuestionnaire(TypedDict):
    id: str
    candidate_id: str
    status: str
    declared_prior_year_billings_usd: float
    declared_prior_year_collections_usd: float
    declared_realization_rate: float
    primary_matter_types: List[str]
    revision_round: int
    entry_count: int
    latest_assessment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClientBookEntry(TypedDict):
    id: str
    questionnaire_id: str
    client_name: str
    relationship_role: str
    client_consent_status: str
    claimed_annual_billings_usd: float
    claimed_portability_pct: float
    claimed_realization_rate: float
    matter_types: List[str]
    status: str
    portable_status: str
    baseline_portable_amount_usd: float
    validated_portable_amount_usd: float
    verified_record_count: int
    created_at: str
    updated_at: str
    version: int


class CollectionRecord(TypedDict):
    """Append-only observation: carries only ``id`` and ``created_at``."""

    id: str
    candidate_id: str
    client_book_entry_id: Optional[str]
    record_type: str
    period_end_date: str
    amount_usd: float
    source: str
    status: str
    created_at: str


class PortabilityAssessment(TypedDict):
    id: str
    questionnaire_id: str
    status: str
    baseline_date: str
    lookback_start_date: str
    governing_basis: str
    entry_count_in_scope: int
    gross_baseline_total_usd: float
    validated_portable_total_usd: float
    declined_portable_total_usd: float
    self_reported_total_usd: float
    variance_pct: float
    top_client_share: float
    top3_client_share: float
    concentration_grade: str
    concentration_haircut_pct: float
    adjusted_portable_total_usd: float
    created_at: str
    updated_at: str
    version: int


class ConflictCheck(TypedDict):
    id: str
    client_book_entry_id: str
    adverse_party_name: str
    affected_matter_types: List[str]
    severity: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictWaiver(TypedDict):
    id: str
    conflict_check_id: str
    waiver_strategy: str
    requested_from_client: str
    response_deadline_date: str
    status: str
    resolution_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatterDeclination(TypedDict):
    id: str
    conflict_check_id: str
    client_book_entry_id: str
    matter_type: str
    foregone_annual_revenue_usd: float
    status: str
    rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationOffer(TypedDict):
    id: str
    candidate_id: str
    portability_assessment_id: str
    created_by_user_id: str
    status: str
    guaranteed_comp_usd: float
    signing_bonus_usd: float
    adjusted_portable_total_snapshot_usd: float
    expected_contribution_usd: float
    total_first_year_comp_usd: float
    search_fee_amount_usd: float
    integration_cost_total_usd: float
    net_first_year_economics_usd: float
    guarantee_true_up_amount_usd: float
    round_number: int
    eligible_voter_count: Optional[int]
    votes_cast_total: int
    active_vote_count: int
    voided_vote_count: int
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict):
    id: str
    offer_id: str
    voter_user_id: str
    decision: str
    round_number: int
    rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IntegrationPlan(TypedDict):
    id: str
    candidate_id: str
    practice_group_id: str
    offer_id: str
    status: str
    onboarding_start_date: str
    onboarding_end_date: str
    planned_standard_rate_usd: float
    cross_sell_target_count: int
    introduction_count: int
    completed_introduction_count: int
    created_at: str
    updated_at: str
    version: int


class CrossSellIntroduction(TypedDict):
    id: str
    integration_plan_id: str
    target_client_name: str
    introducing_partner_name: str
    slot_start_at: str
    slot_end_at: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReview(TypedDict):
    id: str
    candidate_id: str
    integration_plan_id: str
    period_start_date: str
    period_end_date: str
    period_days: int
    variance_basis: str
    realized_standard_rate_usd: float
    actual_collections_usd: float
    plan_target_usd: float
    plan_target_adjusted_usd: float
    variance_usd: float
    attainment_pct: float
    performance_flag: str
    cross_sell_credit_count: int
    created_at: str
    updated_at: str
    version: int
