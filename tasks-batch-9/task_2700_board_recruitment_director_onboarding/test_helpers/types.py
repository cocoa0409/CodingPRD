"""Domain types for the Board Recruitment & Director Onboarding API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    GOVERNANCE_STAFF = "GovernanceStaff"
    CORPORATE_SECRETARY = "CorporateSecretary"
    COMMITTEE_CHAIR = "CommitteeChair"
    COMMITTEE_MEMBER = "CommitteeMember"
    SEATED_DIRECTOR = "SeatedDirector"
    SEARCH_FIRM_PARTNER = "SearchFirmPartner"


# --------------------------------------------------------------------------
# Enumerated vocabularies (PRD 2.11)
# --------------------------------------------------------------------------
class GovernancePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class IndependenceStandard(str, Enum):
    BRIGHT_LINE = "BRIGHT_LINE"
    ENHANCED = "ENHANCED"


class SkillCategoryCriticality(str, Enum):
    CORE = "CORE"
    STRATEGIC = "STRATEGIC"
    EMERGING = "EMERGING"


class SearchFirmFeeModel(str, Enum):
    RETAINER = "RETAINER"
    CONTINGENT = "CONTINGENT"


class DirectorServiceStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    SEATED = "SEATED"
    RETIREMENT_NOTICED = "RETIREMENT_NOTICED"
    RETIRED = "RETIRED"
    RESIGNED = "RESIGNED"
    NOT_RENOMINATED = "NOT_RENOMINATED"


class DirectorComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVERBOARDED = "OVERBOARDED"
    OWNERSHIP_SHORTFALL = "OWNERSHIP_SHORTFALL"
    EDUCATION_DELINQUENT = "EDUCATION_DELINQUENT"


class DirectorOnboardingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class RatingValidationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    VALIDATED = "VALIDATED"


class CandidateStatus(str, Enum):
    SOURCED = "SOURCED"
    SCREENING = "SCREENING"
    SCREEN_PASSED = "SCREEN_PASSED"
    INTERVIEWING = "INTERVIEWING"
    REFERENCE_CHECK = "REFERENCE_CHECK"
    SLATE_ELIGIBLE = "SLATE_ELIGIBLE"
    NOMINATED = "NOMINATED"
    ELECTED = "ELECTED"
    NOT_ELECTED = "NOT_ELECTED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SourceChannel(str, Enum):
    SEARCH_FIRM = "SEARCH_FIRM"
    NETWORK_REFERRAL = "NETWORK_REFERRAL"
    SHAREHOLDER_PROPOSAL = "SHAREHOLDER_PROPOSAL"
    UNIVERSAL_PROXY_NOMINATION = "UNIVERSAL_PROXY_NOMINATION"


class RejectionReasonCode(str, Enum):
    INDEPENDENCE_FAILED = "INDEPENDENCE_FAILED"
    ADVERSE_REFERENCE = "ADVERSE_REFERENCE"
    INTERLOCK_LIMIT = "INTERLOCK_LIMIT"
    OVERBOARDING = "OVERBOARDING"
    RETIREMENT_AGE = "RETIREMENT_AGE"


class IndependenceResult(str, Enum):
    PENDING = "PENDING"
    INDEPENDENT = "INDEPENDENT"
    NOT_INDEPENDENT = "NOT_INDEPENDENT"


class ExternalSeatRole(str, Enum):
    DIRECTOR = "DIRECTOR"
    CHAIR = "CHAIR"
    CEO_AND_DIRECTOR = "CEO_AND_DIRECTOR"


class ExternalDirectorshipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class IndependenceScreenStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DETERMINED_INDEPENDENT = "DETERMINED_INDEPENDENT"
    DETERMINED_NOT_INDEPENDENT = "DETERMINED_NOT_INDEPENDENT"
    VOIDED = "VOIDED"


class ScreenDetermination(str, Enum):
    PENDING = "PENDING"
    INDEPENDENT = "INDEPENDENT"
    NOT_INDEPENDENT = "NOT_INDEPENDENT"


class DisqualifyingFactorCode(str, Enum):
    PAYMENT_MATERIALITY = "PAYMENT_MATERIALITY"
    RECENT_EMPLOYMENT = "RECENT_EMPLOYMENT"
    FAMILY_EMPLOYMENT = "FAMILY_EMPLOYMENT"
    AUDITOR_AFFILIATION = "AUDITOR_AFFILIATION"
    CHARITABLE_MATERIALITY = "CHARITABLE_MATERIALITY"


class InterviewModality(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIDEO = "VIDEO"


class InterviewRecommendation(str, Enum):
    ADVANCE = "ADVANCE"
    HOLD = "HOLD"
    DECLINE = "DECLINE"


class InterviewSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CommitteeCode(str, Enum):
    AUDIT = "AUDIT"
    COMPENSATION = "COMPENSATION"
    NOMINATING_GOVERNANCE = "NOMINATING_GOVERNANCE"
    RISK = "RISK"


class CommitteeStatus(str, Enum):
    AT_STRENGTH = "AT_STRENGTH"
    UNDER_STRENGTH = "UNDER_STRENGTH"
    SUSPENDED = "SUSPENDED"


class CommitteeSeatRole(str, Enum):
    MEMBER = "MEMBER"
    CHAIR = "CHAIR"


class CommitteeAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    REVOKED = "REVOKED"


class AssignmentEndedReasonCode(str, Enum):
    RETIREMENT_NOTICE = "RETIREMENT_NOTICE"
    REVOCATION = "REVOCATION"


class NominationSlateStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    APPROVED = "APPROVED"
    FILED = "FILED"
    ELECTION_RECORDED = "ELECTION_RECORDED"
    ABANDONED = "ABANDONED"


class SlateNomineeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"
    ELECTED = "ELECTED"
    NOT_ELECTED = "NOT_ELECTED"


class FeeTier(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"


class Ballot(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"
    RECUSED = "RECUSED"


class CommitteeVoteStatus(str, Enum):
    CAST = "CAST"
    VOIDED_BY_REVISION = "VOIDED_BY_REVISION"


class OnboardingItemCategory(str, Enum):
    BUSINESS_ORIENTATION = "BUSINESS_ORIENTATION"
    COMMITTEE_ONBOARDING = "COMMITTEE_ONBOARDING"
    DOCUMENT_ACCESS = "DOCUMENT_ACCESS"
    CONTINUING_EDUCATION = "CONTINUING_EDUCATION"


class OnboardingItemStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class CompAwardStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


# Request-only vocabularies (PRD 2.11 final paragraph)
class NoticeType(str, Enum):
    RETIREMENT = "RETIREMENT"
    RESIGNATION = "RESIGNATION"


class InterviewResolution(str, Enum):
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SlateDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABANDON = "ABANDON"


class GapAnalysisVariant(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    VALIDATED_ONLY = "VALIDATED_ONLY"


class GapSeverity(str, Enum):
    CRITICAL_GAP = "CRITICAL_GAP"
    MINOR_GAP = "MINOR_GAP"
    COVERED = "COVERED"


# --------------------------------------------------------------------------
# Entity shapes (PRD 2.4 + section 3)
# --------------------------------------------------------------------------
class GovernancePolicy(TypedDict):
    id: str
    cycle_year: int
    effective_from: str
    authorized_seats: int
    independence_min_pct: float
    independence_standard: str
    bright_line_payment_floor_cents: int
    bright_line_revenue_pct: float
    bright_line_lookback_years: int
    enhanced_lookback_years: int
    enhanced_charitable_pct: float
    max_public_boards_default: int
    max_public_boards_sitting_ceo: int
    interlock_max_shared_boards: int
    mandatory_retirement_age: int
    max_tenure_years: int
    min_completed_interviews: int
    quorum_size: int
    approval_threshold_pct: float
    annual_cash_retainer_cents: int
    committee_member_fee_cents: int
    committee_chair_premium_cents: int
    equity_grant_value_cents: int
    ownership_multiple: float
    ownership_grace_years: int
    education_hours_required: float
    readiness_min_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Leaner record: immutable reference data, id + created_at only (PRD 2.4)
class SkillCategory(TypedDict):
    id: str
    code: str
    name: str
    strategic_weight: float
    risk_oversight: bool
    required_min_directors: int
    criticality: str
    created_at: str


# Leaner record: immutable reference data, id + created_at only (PRD 2.4)
class ExternalCompany(TypedDict):
    id: str
    name: str
    ticker: str
    is_public: bool
    is_competitor: bool
    gross_revenue_cents: int
    created_at: str


class SearchFirm(TypedDict):
    id: str
    name: str
    contact_email: str
    fee_model: str
    retainer_fee_cents: int
    placement_fee_pct: float
    placement_fee_tier2_pct: float
    placed_nominee_count: int
    committed_fee_cents: int
    retainer_credit_applied_cents: int
    net_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class Director(TypedDict):
    id: str
    full_name: str
    email: str
    birth_date: str
    appointed_on: str
    source_candidate_id: Optional[str]
    is_management: bool
    is_sitting_ceo_elsewhere: bool
    is_independent: bool
    shares_held: int
    service_status: str
    compliance_status: str
    onboarding_status: str
    onboarding_completion_pct: float
    age_years: int
    tenure_years: int
    external_public_board_count: int
    education_hours_cycle: float
    retirement_notice_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DirectorSkillRating(TypedDict):
    id: str
    director_id: str
    skill_category_id: str
    self_rating: int
    validated_rating: Optional[int]
    validation_status: str
    effective_rating: int
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    full_name: str
    email: str
    birth_date: str
    source_channel: str
    search_firm_id: Optional[str]
    referring_director_id: Optional[str]
    shareholder_proponent_name: Optional[str]
    is_sitting_ceo: bool
    target_annual_comp_cents: int
    status: str
    rejection_reason_code: Optional[str]
    independence_result: str
    completed_interview_count: int
    interview_score_avg: float
    external_public_board_count: int
    interlock_shared_board_count: int
    readiness_score: float
    reference_check_count: int
    adverse_reference_found: bool
    deferred_cycle_year: Optional[int]
    interview_round: int
    created_at: str
    updated_at: str
    version: int


class ExternalDirectorship(TypedDict):
    id: str
    director_id: Optional[str]
    candidate_id: Optional[str]
    external_company_id: str
    seat_role: str
    is_audit_chair: bool
    start_on: str
    end_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IndependenceScreen(TypedDict):
    id: str
    candidate_id: str
    standard_applied: Optional[str]
    payments_to_company_cents: int
    recipient_gross_revenue_cents: int
    prior_employment_end_on: Optional[str]
    family_member_employed: bool
    auditor_affiliation: bool
    charitable_contributions_cents: int
    company_gross_revenue_cents: int
    bright_line_fail_count: int
    qualitative_fail_count: int
    determination: str
    disqualifying_factor_code: Optional[str]
    status: str
    submitted_at: Optional[str]
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterviewSession(TypedDict):
    id: str
    candidate_id: str
    interviewer_director_id: str
    start_at: str
    end_at: str
    modality: str
    interview_round: int
    score: Optional[int]
    recommendation: Optional[str]
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict):
    id: str
    code: str
    name: str
    authorized_seats: int
    min_seats: int
    requires_all_independent: bool
    requires_financial_expert: bool
    filled_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeAssignment(TypedDict):
    id: str
    committee_id: str
    director_id: str
    seat_role: str
    term_start_on: str
    term_end_on: str
    status: str
    ended_reason_code: Optional[str]
    activated_at: Optional[str]
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NominationSlate(TypedDict):
    id: str
    cycle_year: int
    seat_count: int
    search_fee_budget_cents: int
    nominee_count: int
    independent_nominee_count: int
    independent_nominee_pct: float
    independence_shortfall: bool
    committed_search_fee_cents: int
    contested: bool
    universal_proxy_applicable: bool
    revision_count: int
    votes_for: int
    votes_against: int
    votes_abstain: int
    votes_recused: int
    approval_pct: float
    quorum_met: bool
    status: str
    filed_at: Optional[str]
    election_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SlateNominee(TypedDict):
    id: str
    slate_id: str
    candidate_id: Optional[str]
    incumbent_director_id: Optional[str]
    ballot_order: int
    is_independent: bool
    placement_fee_cents: int
    fee_tier_applied: Optional[str]
    nominee_ordinal: int
    status: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict):
    id: str
    slate_id: str
    voting_director_id: str
    ballot: str
    rationale: str
    recusal_required: bool
    status: str
    cast_at: str
    created_at: str
    updated_at: str
    version: int


class OnboardingItem(TypedDict):
    id: str
    director_id: str
    module_code: str
    category: str
    is_required: bool
    credit_hours: float
    due_on: Optional[str]
    status: str
    completed_at: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DirectorCompensationAward(TypedDict):
    id: str
    director_id: str
    cycle_year: int
    service_start_on: str
    service_end_on: str
    share_price_cents: int
    shares_held: int
    service_days: int
    committee_member_seat_count: int
    committee_chair_seat_count: int
    prorated_cash_retainer_cents: int
    committee_fees_cents: int
    equity_value_cents: int
    pre_offset_total_cents: int
    excess_offset_pct: float
    excess_offset_cents: int
    total_cents: int
    ownership_requirement_cents: int
    ownership_actual_cents: int
    ownership_compliant: bool
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GapAnalysisCategoryRow(TypedDict):
    skill_category_id: str
    code: str
    criticality: str
    required_min_directors: int
    covered_director_count: int
    gap: int
    weighted_gap: float
    severity: str


class GapAnalysis(TypedDict):
    variant: str
    seated_director_count: int
    category_count: int
    board_gap_index: float
    priority_category_code: Optional[str]
    categories: List[GapAnalysisCategoryRow]
