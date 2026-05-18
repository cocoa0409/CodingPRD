"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — common-fields vs lean-fields entities:

    "Most entities — Unit, Member, AssessmentCharge, ACCRequest, Violation,
    BoardResolution, ElectionCycle, Lien, and ReserveStudy — carry the
    common audit triplet id, created_at, updated_at, plus an integer version.
    A second, smaller shape applies to AssessmentCycle, Payment, ACCVote,
    Candidate, and Ballot: these entities carry only id and created_at and
    have neither an updated_at nor a version field, because they are either
    pure event records (votes, payments, ballots) or because their lifecycle
    is expressed through their child rows rather than through self-mutation."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MEMBER = "Member"
    SECRETARY_ROLE = "SecretaryRole"
    TREASURER_ROLE = "TreasurerRole"
    PRESIDENT_ROLE = "PresidentRole"
    DIRECTOR_ROLE = "DirectorRole"


# ---------------------------------------------------------------------------
# Status enums — PRD §3 state machines
# ---------------------------------------------------------------------------
class UnitLienStatus(str, Enum):
    NONE = "NONE"
    NOTICE_SENT = "NOTICE_SENT"
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"


class MemberBoardRole(str, Enum):
    NONE = "NONE"
    PRESIDENT = "PRESIDENT"
    TREASURER = "TREASURER"
    SECRETARY = "SECRETARY"
    DIRECTOR = "DIRECTOR"


class AssessmentCycleType(str, Enum):
    REGULAR = "REGULAR"
    SPECIAL = "SPECIAL"


class AssessmentCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class AssessmentChargeStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WRITTEN_OFF = "WRITTEN_OFF"


class ACCRequestCategory(str, Enum):
    APPEARANCE = "APPEARANCE"
    LANDSCAPING = "LANDSCAPING"


class ACCRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    AUTO_APPROVED = "AUTO_APPROVED"
    AUTO_DENIED = "AUTO_DENIED"
    WITHDRAWN = "WITHDRAWN"


class VoteChoice(str, Enum):
    YES = "YES"
    NO = "NO"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    FINED = "FINED"
    WAIVED = "WAIVED"


class BoardResolutionSubject(str, Enum):
    SPECIAL_ASSESSMENT = "SPECIAL_ASSESSMENT"
    RESERVE_STUDY_ADOPTION = "RESERVE_STUDY_ADOPTION"
    FINE_WAIVER = "FINE_WAIVER"
    LIEN_RECORDATION = "LIEN_RECORDATION"
    LIEN_RELEASE = "LIEN_RELEASE"


class BoardResolutionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXECUTED = "EXECUTED"


class ElectionSeat(str, Enum):
    PRESIDENT = "PRESIDENT"
    TREASURER = "TREASURER"
    SECRETARY = "SECRETARY"
    DIRECTOR = "DIRECTOR"


class ElectionStatus(str, Enum):
    NOMINATION = "NOMINATION"
    VOTING = "VOTING"
    TALLIED = "TALLIED"
    CERTIFIED = "CERTIFIED"
    FAILED_QUORUM = "FAILED_QUORUM"
    VOIDED = "VOIDED"


class LienStatus(str, Enum):
    NOTICE_SENT = "NOTICE_SENT"
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"


class ReserveStudyPosture(str, Enum):
    OK = "OK"
    RESTRICTED = "RESTRICTED"
    SPECIAL_ASSESSMENT_REQUIRED = "SPECIAL_ASSESSMENT_REQUIRED"


class ReserveStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities (id, created_at, updated_at,
# version) per PRD §2.4
# ---------------------------------------------------------------------------
class Unit(TypedDict, total=False):
    id: str
    address: str
    owner_member_id: str
    share_factor: float
    mortgage_holder: Optional[str]
    lien_status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    eligible_to_vote: bool
    board_role: str
    total_overdue_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AssessmentCharge(TypedDict, total=False):
    id: str
    cycle_id: str
    unit_id: str
    principal_cents: int
    late_fee_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ACCRequest(TypedDict, total=False):
    id: str
    unit_id: str
    submitted_by_member_id: str
    category: str
    description: str
    submitted_at: str
    deemed_decision_deadline: str
    status: str
    yes_votes: int
    no_votes: int
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    unit_id: str
    opened_by_member_id: str
    opened_at: str
    cure_deadline: str
    occurrence_index: int
    fine_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardResolution(TypedDict, total=False):
    id: str
    subject: str
    target_id: str
    yes_votes: int
    no_votes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ElectionCycle(TypedDict, total=False):
    id: str
    seat: str
    nomination_open_at: str
    voting_open_at: str
    voting_close_at: str
    quorum_pct: float
    eligible_voter_count_at_open: Optional[int]
    status: str
    winner_candidate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict, total=False):
    id: str
    unit_id: str
    principal_cents_at_record: Optional[int]
    mortgage_holder_at_record: Optional[str]
    recorded_at: Optional[str]
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReserveStudy(TypedDict, total=False):
    id: str
    study_year: int
    components: List[dict]
    current_reserve_balance_cents: int
    full_funding_target_cents: int
    funded_ratio: Optional[float]
    posture: str
    adopted_resolution_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean entities — PRD §2.4: AssessmentCycle, Payment, ACCVote, Candidate,
# Ballot carry ONLY id + created_at (no updated_at, no version).
# ---------------------------------------------------------------------------
class AssessmentCycle(TypedDict, total=False):
    id: str
    cycle_type: str
    period_start: str
    due_date: str
    total_levy_cents: int
    approval_resolution_id: Optional[str]
    status: str
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    member_id: str
    amount_cents: int
    allocations: List[dict]
    created_at: str


class ACCVote(TypedDict, total=False):
    id: str
    request_id: str
    voter_member_id: str
    vote: str
    cast_at: str
    created_at: str


class Candidate(TypedDict, total=False):
    id: str
    election_id: str
    member_id: str
    nominated_at: str
    vote_count: int
    created_at: str


class Ballot(TypedDict, total=False):
    id: str
    election_id: str
    voter_member_id: str
    candidate_id: str
    created_at: str


__all__ = [
    "UserRole",
    "UnitLienStatus",
    "MemberBoardRole",
    "AssessmentCycleType",
    "AssessmentCycleStatus",
    "AssessmentChargeStatus",
    "ACCRequestCategory",
    "ACCRequestStatus",
    "VoteChoice",
    "ViolationStatus",
    "BoardResolutionSubject",
    "BoardResolutionStatus",
    "ElectionSeat",
    "ElectionStatus",
    "LienStatus",
    "ReserveStudyPosture",
    "ReserveStudyStatus",
    "Unit",
    "Member",
    "AssessmentCharge",
    "ACCRequest",
    "Violation",
    "BoardResolution",
    "ElectionCycle",
    "Lien",
    "ReserveStudy",
    "AssessmentCycle",
    "Payment",
    "ACCVote",
    "Candidate",
    "Ballot",
]
