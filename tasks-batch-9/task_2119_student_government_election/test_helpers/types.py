"""Domain types for the Student Government Election API.

Every resource in this system — elections, offices, students, candidacies,
petition signatures, campaign expenses, compliance cases, referenda, ballots,
ballot lines, votes and appeals — carries the same four system-managed
properties (`id`, `created_at`, `updated_at`, `version`), so every TypedDict
below lists all four (PRD §2.6).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ELECTION_COMMISSIONER = "ElectionCommissioner"
    FACULTY_ADVISOR = "FacultyAdvisor"
    REGISTRAR = "Registrar"
    CANDIDATE = "Candidate"
    STUDENT_VOTER = "StudentVoter"


# ─── Status enums ─────────────────────────────────────────────────────────────

class ElectionStatus(str, Enum):
    DRAFT = "DRAFT"
    PETITIONING = "PETITIONING"
    BALLOT_BUILDING = "BALLOT_BUILDING"
    BALLOT_PUBLISHED = "BALLOT_PUBLISHED"
    VOTING_OPEN = "VOTING_OPEN"
    VOTING_CLOSED = "VOTING_CLOSED"
    TALLYING = "TALLYING"
    CERTIFIED = "CERTIFIED"
    RUNOFF_SCHEDULED = "RUNOFF_SCHEDULED"
    CLOSED = "CLOSED"


class BallotIntegrityStatus(str, Enum):
    INTACT = "INTACT"
    RECOUNT_REQUIRED = "RECOUNT_REQUIRED"


class OfficeStatus(str, Enum):
    OPEN = "OPEN"
    CONTESTED = "CONTESTED"
    RUNOFF_REQUIRED = "RUNOFF_REQUIRED"
    DECIDED = "DECIDED"
    VACANT_SEAT = "VACANT_SEAT"


class ClassYear(str, Enum):
    FRESHMAN = "FRESHMAN"
    SOPHOMORE = "SOPHOMORE"
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    GRADUATE = "GRADUATE"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    LEAVE = "LEAVE"
    WITHDRAWN = "WITHDRAWN"


class CandidacyStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    ELIGIBLE = "ELIGIBLE"
    PETITION_DEFICIENT = "PETITION_DEFICIENT"
    SLATE_SUSPENDED = "SLATE_SUSPENDED"
    ON_BALLOT = "ON_BALLOT"
    RUNOFF_QUALIFIED = "RUNOFF_QUALIFIED"
    ELECTED = "ELECTED"
    ELIMINATED = "ELIMINATED"
    VACATED = "VACATED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class TransitionStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    TRAINING_COMPLETE = "TRAINING_COMPLETE"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class SignatureStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class EligibilityResult(str, Enum):
    UNKNOWN = "UNKNOWN"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_NOT_ENROLLED = "INELIGIBLE_NOT_ENROLLED"
    INELIGIBLE_CLASS_YEAR = "INELIGIBLE_CLASS_YEAR"
    INELIGIBLE_HOLD = "INELIGIBLE_HOLD"


class ExpenseCategory(str, Enum):
    POSTER = "POSTER"
    DIGITAL = "DIGITAL"
    MERCH = "MERCH"
    EVENT = "EVENT"


class ExpenseStatus(str, Enum):
    REPORTED = "REPORTED"
    APPROVED = "APPROVED"
    REVERSED = "REVERSED"


class CaseSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class CaseStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class DraftingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED_FOR_BALLOT = "APPROVED_FOR_BALLOT"
    ON_BALLOT = "ON_BALLOT"


class OutcomeStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    QUORUM_NOT_MET = "QUORUM_NOT_MET"


class BallotStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class BallotLineType(str, Enum):
    CANDIDATE = "CANDIDATE"
    REFERENDUM = "REFERENDUM"


class BallotLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class VoteStatus(str, Enum):
    CAST = "CAST"
    VOIDED = "VOIDED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"


class RemedyRequested(str, Enum):
    RECOUNT = "RECOUNT"
    REINSTATEMENT = "REINSTATEMENT"
    VOID_ELECTION = "VOID_ELECTION"


class ReferendumChoice(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


class AdjudicationOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ReviewOutcome(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


# ─── Entity shapes ────────────────────────────────────────────────────────────

class Election(TypedDict):
    id: str
    title: str
    academic_year: str
    status: str
    current_round: int
    petition_deadline: str
    quiet_period_hours: int
    voting_opens_at: Optional[str]
    voting_closes_at: Optional[str]
    spending_cap_cents: int
    poster_cap: int
    quorum_pct: float
    runoff_threshold_pct: float
    eligible_voter_count: int
    ballots_cast_count: int
    turnout_pct: float
    runoff_required_office_count: int
    ballot_integrity_status: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Office(TypedDict):
    id: str
    election_id: str
    name: str
    seat_count: int
    eligible_class_years: List[str]
    required_signature_count: int
    min_gpa: float
    min_credits: int
    required_training_modules: int
    term_start_date: str
    term_end_date: str
    status: str
    filled_seat_count: int
    valid_votes_count: int
    abstain_votes_count: int
    invalidated_votes_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    student_number: str
    class_year: str
    enrollment_status: str
    gpa: float
    credits_completed: int
    disciplinary_hold: bool
    created_at: str
    updated_at: str
    version: int


class Candidacy(TypedDict):
    id: str
    election_id: str
    office_id: str
    student_id: str
    slate_leader_candidacy_id: Optional[str]
    statement: Optional[str]
    status: str
    transition_status: str
    training_modules_completed: int
    ballot_position: Optional[int]
    petition_signature_total_count: int
    petition_signature_valid_count: int
    petition_signature_ineligible_count: int
    petition_signature_pending_count: int
    petition_signature_rejected_count: int
    petition_signature_voided_count: int
    spending_reported_cents: int
    spending_committed_cents: int
    spending_reversed_cents: int
    spending_final_cents: Optional[int]
    poster_count: int
    penalty_points_total: int
    slate_snapshot_member_ids: List[str]
    raw_votes_count: int
    certified_votes_count: int
    provisional_share_pct: float
    certified_share_pct: float
    disqualified_reason: Optional[str]
    term_start_date: Optional[str]
    term_end_date: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PetitionSignature(TypedDict):
    id: str
    candidacy_id: str
    signer_student_id: str
    signed_at: str
    status: str
    eligibility_result: str
    reject_reason: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CampaignExpense(TypedDict):
    id: str
    candidacy_id: str
    category: str
    amount_cents: int
    quantity: int
    shared_with_slate: bool
    incurred_at: str
    venue_code: Optional[str]
    event_starts_at: Optional[str]
    event_ends_at: Optional[str]
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict):
    id: str
    election_id: str
    candidacy_id: str
    rule_code: str
    severity: str
    description: str
    status: str
    penalty_points: int
    prior_upheld_count: int
    timing_factor_applied: float
    overspend_points_applied: int
    filed_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    upheld_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referendum(TypedDict):
    id: str
    election_id: str
    title: str
    article_reference: str
    body_text: str
    approval_threshold_pct: float
    drafting_status: str
    outcome_status: str
    yes_votes_count: int
    no_votes_count: int
    abstain_votes_count: int
    approval_pct: float
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict):
    id: str
    election_id: str
    round: int
    status: str
    line_count: int
    active_line_count: int
    locked_at: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BallotLine(TypedDict):
    id: str
    ballot_id: str
    office_id: Optional[str]
    candidacy_id: Optional[str]
    referendum_id: Optional[str]
    line_type: str
    position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vote(TypedDict):
    id: str
    election_id: str
    ballot_id: str
    student_id: str
    round: int
    selections: List[dict]
    status: str
    cast_at: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    election_id: str
    candidacy_id: str
    compliance_case_id: Optional[str]
    grounds: str
    remedy_requested: str
    status: str
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    filed_at: str
    created_at: str
    updated_at: str
    version: int
