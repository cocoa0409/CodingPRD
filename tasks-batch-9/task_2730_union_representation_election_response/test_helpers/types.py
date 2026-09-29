"""Domain types for the Union Representation Election Response API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    LABOR_RELATIONS_DIRECTOR = "LaborRelationsDirector"
    HR_DATA_ANALYST = "HRDataAnalyst"
    EMPLOYMENT_COUNSEL = "EmploymentCounsel"
    SUPERVISOR_TRAINER = "SupervisorTrainer"
    PLANT_SUPERVISOR = "PlantSupervisor"
    BOARD_AGENT = "BoardAgent"
    UNION_REPRESENTATIVE = "UnionRepresentative"


ALL_ROLE_NAMES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class CaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCOPE_ANALYSIS = "SCOPE_ANALYSIS"
    SOI_VERIFIED = "SOI_VERIFIED"
    ELECTION_SET = "ELECTION_SET"
    VOTING_CLOSED = "VOTING_CLOSED"
    TALLY_POSTED = "TALLY_POSTED"
    OBJECTIONS_PENDING = "OBJECTIONS_PENDING"
    RERUN_DIRECTED = "RERUN_DIRECTED"
    CERTIFIED = "CERTIFIED"
    DISMISSED = "DISMISSED"


class CasePosture(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"
    IMPOUNDED = "IMPOUNDED"


class PetitionType(str, Enum):
    RC = "RC"
    RM = "RM"
    RD = "RD"


class ShowingVerdict(str, Enum):
    PENDING = "PENDING"
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class ShowingHeadcountBasis(str, Enum):
    AS_PETITIONED = "AS_PETITIONED"
    AS_RULED = "AS_RULED"


class CertificationOutcome(str, Enum):
    NONE = "NONE"
    CERTIFICATION_OF_REPRESENTATIVE = "CERTIFICATION_OF_REPRESENTATIVE"
    CERTIFICATION_OF_RESULTS = "CERTIFICATION_OF_RESULTS"


class ScopeRuling(str, Enum):
    PENDING = "PENDING"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    MOOT = "MOOT"


class ScoringStandard(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    OVERWHELMING = "OVERWHELMING"
    ACCRETION = "ACCRETION"


class CoiRecommendation(str, Enum):
    SHARED_COMMUNITY = "SHARED_COMMUNITY"
    CONTESTED_COMMUNITY = "CONTESTED_COMMUNITY"
    DISTINCT_COMMUNITY = "DISTINCT_COMMUNITY"
    MANDATORY_EXCLUSION = "MANDATORY_EXCLUSION"


class ScopePosition(str, Enum):
    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    STIPULATED_APPROVED = "STIPULATED_APPROVED"
    HEARING_REQUESTED = "HEARING_REQUESTED"
    DIRECTED = "DIRECTED"
    VOID = "VOID"


class AgreementRoute(str, Enum):
    PENDING = "PENDING"
    STIPULATED = "STIPULATED"
    DIRECTED = "DIRECTED"


class AgreementType(str, Enum):
    STIPULATED = "STIPULATED"
    CONSENT = "CONSENT"


class VotingMethod(str, Enum):
    MANUAL = "MANUAL"
    MAIL = "MAIL"
    MIXED = "MIXED"


class VoterListStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DEFICIENT = "DEFICIENT"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ListGrade(str, Enum):
    COMPLIANT = "COMPLIANT"
    MINOR_DEFECT = "MINOR_DEFECT"
    MATERIAL_DEFECT = "MATERIAL_DEFECT"
    GROSSLY_DEFICIENT = "GROSSLY_DEFICIENT"


class ListDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN_FOR_CURE = "RETURN_FOR_CURE"
    REJECT = "REJECT"


class OnLeaveType(str, Enum):
    NONE = "NONE"
    SICK = "SICK"
    FMLA = "FMLA"
    MILITARY = "MILITARY"
    PERMANENT_LAYOFF = "PERMANENT_LAYOFF"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    CHALLENGED = "CHALLENGED"


class IneligibilityReason(str, Enum):
    OUTSIDE_UNIT = "OUTSIDE_UNIT"
    HIRED_AFTER_PAYROLL_PERIOD = "HIRED_AFTER_PAYROLL_PERIOD"
    TERMINATED_BEFORE_ELECTION = "TERMINATED_BEFORE_ELECTION"
    PERMANENT_LAYOFF = "PERMANENT_LAYOFF"


class TrainingStatus(str, Enum):
    UNTRAINED = "UNTRAINED"
    TRAINED = "TRAINED"


class ViolationCode(str, Enum):
    THREAT = "THREAT"
    INTERROGATION = "INTERROGATION"
    PROMISE_OF_BENEFIT = "PROMISE_OF_BENEFIT"
    SURVEILLANCE = "SURVEILLANCE"
    SOLICITATION_RULE_DISPARITY = "SOLICITATION_RULE_DISPARITY"


class Channel(str, Enum):
    EMAIL = "EMAIL"
    LETTER = "LETTER"
    DIGITAL_POST = "DIGITAL_POST"
    SMALL_GROUP_MEETING = "SMALL_GROUP_MEETING"
    CAPTIVE_AUDIENCE_MEETING = "CAPTIVE_AUDIENCE_MEETING"


class AudienceScope(str, Enum):
    UNIT_WIDE = "UNIT_WIDE"
    CLASSIFICATION = "CLASSIFICATION"
    INDIVIDUAL = "INDIVIDUAL"


class CommunicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_LEGAL_REVIEW = "PENDING_LEGAL_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    BLOCKED = "BLOCKED"


class BlockedReason(str, Enum):
    PRESENTER_DECERTIFIED = "PRESENTER_DECERTIFIED"
    RERUN_BLACKOUT = "RERUN_BLACKOUT"
    POSTURE_BLOCKED = "POSTURE_BLOCKED"
    CASE_DISMISSED = "CASE_DISMISSED"


class ReviewDisposition(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"


class RoundStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUSPENDED = "SUSPENDED"
    POLLS_OPEN = "POLLS_OPEN"
    POLLS_CLOSED = "POLLS_CLOSED"
    TALLY_POSTED = "TALLY_POSTED"
    TALLY_REVISED = "TALLY_REVISED"
    SET_ASIDE = "SET_ASIDE"
    ROUND_CERTIFIED = "ROUND_CERTIFIED"


class PollSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class SessionMethod(str, Enum):
    MANUAL = "MANUAL"
    MAIL = "MAIL"


class ChallengerParty(str, Enum):
    EMPLOYER = "EMPLOYER"
    UNION = "UNION"
    BOARD = "BOARD"


class ChallengeBasis(str, Enum):
    SUPERVISOR = "SUPERVISOR"
    NOT_ON_LIST = "NOT_ON_LIST"
    OUTSIDE_UNIT = "OUTSIDE_UNIT"
    IDENTITY = "IDENTITY"
    LAID_OFF = "LAID_OFF"


class BallotResolution(str, Enum):
    OPEN = "OPEN"
    COUNTED_FOR = "COUNTED_FOR"
    COUNTED_AGAINST = "COUNTED_AGAINST"
    VOIDED = "VOIDED"
    WITHDRAWN = "WITHDRAWN"


class ObjectionStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"


class ObjectionGround(str, Enum):
    PROHIBITED_SUPERVISOR_CONDUCT = "PROHIBITED_SUPERVISOR_CONDUCT"
    CAPTIVE_AUDIENCE_TIMING = "CAPTIVE_AUDIENCE_TIMING"
    LIST_DEFICIENCY = "LIST_DEFICIENCY"
    POLLING_IRREGULARITY = "POLLING_IRREGULARITY"
    THIRD_PARTY_CONDUCT = "THIRD_PARTY_CONDUCT"


class ObjectionDisposition(str, Enum):
    SUSTAIN = "SUSTAIN"
    OVERRULE = "OVERRULE"


class ChargeStatus(str, Enum):
    FILED = "FILED"
    MERIT_FOUND = "MERIT_FOUND"
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"


class ChargingParty(str, Enum):
    UNION = "UNION"
    EMPLOYER = "EMPLOYER"
    INDIVIDUAL = "INDIVIDUAL"


class SectionCode(str, Enum):
    S8A1 = "8A1"
    S8A3 = "8A3"
    S8A5 = "8A5"
    S8B1A = "8B1A"


class RemedyCode(str, Enum):
    NOTICE_POSTING = "NOTICE_POSTING"
    REINSTATEMENT = "REINSTATEMENT"
    BARGAINING_ORDER = "BARGAINING_ORDER"
    RERUN_ELECTION = "RERUN_ELECTION"


class SettlementType(str, Enum):
    NON_BOARD = "NON_BOARD"
    FORMAL = "FORMAL"


class ChargeDetermination(str, Enum):
    MERIT = "MERIT"
    DISMISS = "DISMISS"


# --------------------------------------------------------------------------
# Entity shapes. Every one of the twelve resource types in this domain carries
# id, created_at, updated_at and version.
# --------------------------------------------------------------------------
class Petition(TypedDict, total=False):
    id: str
    case_number: str
    petition_type: str
    union_name: str
    filed_date: str
    proposed_unit_description: str
    claimed_employee_count: int
    payroll_period_end: str
    case_status: str
    case_posture: str
    total_classified_headcount: int
    included_headcount: int
    excluded_headcount: int
    pending_headcount: int
    core_avg_hourly_wage_cents: Optional[int]
    core_wage_locked_at: Optional[str]
    submitted_card_count: int
    duplicate_card_count: int
    undated_card_count: int
    stale_card_count: int
    nonunit_card_count: int
    valid_card_count: Optional[int]
    showing_of_interest_pct: Optional[float]
    showing_headcount_basis: Optional[str]
    showing_verdict: str
    retraining_required: bool
    certification_outcome: str
    certified_at: Optional[str]
    certified_round_id: Optional[str]
    bargaining_obligation_start_at: Optional[str]
    bargaining_obligation_end_at: Optional[str]
    certification_year_end_at: Optional[str]
    election_bar_end_at: Optional[str]
    decert_window_open_at: Optional[str]
    notice_posting_end_at: Optional[str]
    pending_objection_count: int
    blocking_charge_count: int
    created_at: str
    updated_at: str
    version: int


class Classification(TypedDict, total=False):
    id: str
    petition_id: str
    code: str
    title: str
    headcount: int
    avg_hourly_wage_cents: int
    shift_code: str
    work_location: str
    supervisory_authority_count: int
    employer_position: str
    union_position: str
    supervision_overlap: int
    skills_overlap: int
    functional_integration: int
    interchange_rate: int
    work_conditions_overlap: int
    wage_proximity: Optional[float]
    coi_score: Optional[float]
    scoring_standard: Optional[str]
    coi_recommendation: Optional[str]
    scope_ruling: str
    ruling_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ElectionAgreement(TypedDict, total=False):
    id: str
    petition_id: str
    agreement_type: str
    proposed_election_date: str
    proposed_voting_method: str
    status: str
    route: str
    approved_election_date: Optional[str]
    voting_method: Optional[str]
    polls_open_at: Optional[str]
    polls_close_at: Optional[str]
    hearing_requested_at: Optional[str]
    hearing_requested_by_party: Optional[str]
    decision_date: Optional[str]
    voter_list_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VoterList(TypedDict, total=False):
    id: str
    petition_id: str
    election_agreement_id: str
    status: str
    due_at: Optional[str]
    submitted_at: Optional[str]
    submitted_by_user_id: Optional[str]
    attested_by_title: Optional[str]
    total_entry_count: int
    complete_entry_count: int
    completeness_pct: Optional[float]
    is_late: bool
    list_grade: Optional[str]
    cure_window_hours: Optional[int]
    cure_deadline_at: Optional[str]
    reviewed_at: Optional[str]
    noted_defects: Optional[List[str]]
    resubmission_count: int
    eligible_voter_count: int
    created_at: str
    updated_at: str
    version: int


class VoterListEntry(TypedDict, total=False):
    id: str
    voter_list_id: str
    classification_id: str
    full_name: str
    hire_date: str
    termination_date: Optional[str]
    home_address: Optional[str]
    personal_email: Optional[str]
    personal_phone: Optional[str]
    shift_code: Optional[str]
    work_location: Optional[str]
    on_leave_type: str
    is_statutory_content_complete: bool
    missing_field_count: int
    eligibility_status: str
    ineligibility_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict, total=False):
    id: str
    petition_id: str
    full_name: str
    job_title: str
    span_of_control: int
    has_hire_fire_authority: bool
    training_status: str
    modules_completed: Optional[List[str]]
    quiz_score: Optional[int]
    training_attempt_count: int
    certified_at: Optional[str]
    violation_count: int
    last_violation_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CampaignCommunication(TypedDict, total=False):
    id: str
    petition_id: str
    presenter_supervisor_id: Optional[str]
    channel: str
    audience_scope: str
    planned_delivery_at: str
    duration_minutes: int
    message_summary: str
    threat_statement_count: int
    contains_interrogation: bool
    contains_promise_of_benefit: bool
    contains_surveillance_reference: bool
    material_claim_count: int
    unsupported_material_claim_count: int
    accuracy_reviewed_at: Optional[str]
    risk_score: int
    peerless_plywood_violation: bool
    status: str
    revision_round: int
    authored_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    escalation_ack: bool
    blocked_reason: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ElectionRound(TypedDict, total=False):
    id: str
    petition_id: str
    election_agreement_id: str
    prior_round_id: Optional[str]
    round_number: int
    voting_method: str
    election_date: str
    polls_open_at: str
    polls_close_at: str
    status: str
    ballots_impounded: bool
    scheduled_session_count: int
    closed_session_count: int
    ballots_cast_total: int
    provisional_votes_for: int
    provisional_votes_against: int
    provisional_void_count: int
    provisional_margin: int
    challenged_open_count: int
    challenged_counted_for_count: int
    challenged_counted_against_count: int
    challenged_voided_count: int
    challenged_withdrawn_count: int
    determinative_challenges: bool
    revised_votes_for: Optional[int]
    revised_votes_against: Optional[int]
    revised_void_count: Optional[int]
    revised_margin: Optional[int]
    valid_votes_cast: Optional[int]
    majority_threshold: Optional[float]
    tally_posted_at: Optional[str]
    tally_revised_at: Optional[str]
    objection_window_close_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PollSession(TypedDict, total=False):
    id: str
    election_round_id: str
    location_code: str
    session_start_at: str
    session_end_at: str
    method: str
    status: str
    votes_for_count: int
    votes_against_count: int
    void_count: int
    challenged_ballot_count: int
    employer_observer_count: int
    union_observer_count: int
    observer_roster: List[dict]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChallengedBallot(TypedDict, total=False):
    id: str
    poll_session_id: str
    voter_list_entry_id: Optional[str]
    challenger_party: str
    basis: str
    resolution: str
    resolved_at: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict, total=False):
    id: str
    election_round_id: str
    related_supervisor_id: Optional[str]
    filed_by_party: str
    ground_code: str
    conduct_occurred_at: str
    alleged_affected_voter_count: int
    description: str
    filed_at: str
    status: str
    affects_results: bool
    rerun_directed: bool
    disposition_rationale: Optional[str]
    ruled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ULPCharge(TypedDict, total=False):
    id: str
    petition_id: str
    related_objection_id: Optional[str]
    charging_party: str
    charged_party: str
    section_code: str
    allegation_summary: str
    conduct_occurred_at: str
    blocking_requested: bool
    status: str
    remedy_code: Optional[str]
    settlement_type: Optional[str]
    notice_posting_days: Optional[int]
    filed_at: str
    determined_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
