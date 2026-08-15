"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class CandidateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TENURED = "TENURED"
    NOT_RENEWED = "NOT_RENEWED"
    WITHDRAWN = "WITHDRAWN"


class CaseStage(str, Enum):
    DOSSIER_ASSEMBLY = "DOSSIER_ASSEMBLY"
    EXTERNAL_REVIEW = "EXTERNAL_REVIEW"
    DEPT_COMMITTEE = "DEPT_COMMITTEE"
    COLLEGE_COMMITTEE = "COLLEGE_COMMITTEE"
    UNIVERSITY_COMMITTEE = "UNIVERSITY_COMMITTEE"
    PROVOST_REVIEW = "PROVOST_REVIEW"
    DECIDED = "DECIDED"
    NOTIFIED = "NOTIFIED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"
    PURGED = "PURGED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    WITHDRAWN = "WITHDRAWN"


class DossierItemStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class DossierCategory(str, Enum):
    TEACHING = "TEACHING"
    RESEARCH = "RESEARCH"
    SERVICE = "SERVICE"


class InvitationStatus(str, Enum):
    SOLICITED = "SOLICITED"
    ACCEPTED = "ACCEPTED"
    LETTER_RECEIVED = "LETTER_RECEIVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class CommitteeLevel(str, Enum):
    DEPARTMENT = "DEPARTMENT"
    COLLEGE = "COLLEGE"
    UNIVERSITY = "UNIVERSITY"


class PassRule(str, Enum):
    STRICT_MAJORITY_OF_CAST = "STRICT_MAJORITY_OF_CAST"
    SUPERMAJORITY_OF_ENTITLED = "SUPERMAJORITY_OF_ENTITLED"


class MemberRole(str, Enum):
    MEMBER = "MEMBER"
    CHAIR = "CHAIR"


class RoundStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    VOTING_OPEN = "VOTING_OPEN"
    TALLYING = "TALLYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Ballot(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"
    RECUSE = "RECUSE"


class VoteStatus(str, Enum):
    CAST = "CAST"
    RETRACTED = "RETRACTED"


class ExtensionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"
    CANCELLED = "CANCELLED"


class ExtensionReason(str, Enum):
    PARENTAL_LEAVE = "PARENTAL_LEAVE"
    MEDICAL_LEAVE = "MEDICAL_LEAVE"
    BEREAVEMENT = "BEREAVEMENT"
    OTHER = "OTHER"


class MidtermStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class MidtermOutcome(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    CONCERNS = "CONCERNS"
    UNSATISFACTORY = "UNSATISFACTORY"


class DecisionKind(str, Enum):
    GRANT_TENURE = "GRANT_TENURE"
    GRANT_PROMOTION = "GRANT_PROMOTION"
    GRANT_BOTH = "GRANT_BOTH"
    DENY = "DENY"
    DEFER = "DEFER"


class DecisionStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    REMANDED = "REMANDED"
    WITHDRAWN = "WITHDRAWN"


class AppealGrounds(str, Enum):
    PROCEDURAL_ERROR = "PROCEDURAL_ERROR"
    NEW_EVIDENCE = "NEW_EVIDENCE"
    DISCRIMINATION = "DISCRIMINATION"
    CAPRICIOUS_EVALUATION = "CAPRICIOUS_EVALUATION"


class AppealResolution(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    REMANDED = "REMANDED"


class Recommendation(str, Enum):
    STRONGLY_SUPPORT = "STRONGLY_SUPPORT"
    SUPPORT = "SUPPORT"
    NEUTRAL = "NEUTRAL"
    OPPOSE = "OPPOSE"
    STRONGLY_OPPOSE = "STRONGLY_OPPOSE"


class ClockPolicy(str, Enum):
    ANNIVERSARY = "ANNIVERSARY"
    DAY_COUNT = "DAY_COUNT"


class TargetRank(str, Enum):
    ASSOCIATE_PROFESSOR = "ASSOCIATE_PROFESSOR"
    FULL_PROFESSOR = "FULL_PROFESSOR"


class UserRole(str, Enum):
    PROVOST_OFFICER = "ProvostOfficer"
    CANDIDATE = "Candidate"
    COMMITTEE_CHAIR = "CommitteeChair"
    COMMITTEE_VOTER = "CommitteeVoter"
    EXTERNAL_REVIEWER = "ExternalReviewer"
    APPEAL_OFFICER = "AppealOfficer"
    RECORDS_OFFICER = "RecordsOfficer"
    SYSTEM_ADMIN = "SystemAdmin"


class Candidate(TypedDict, total=False):
    id: str
    full_name: str
    employee_id: str
    department: str
    college: str
    tenure_clock_start: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TenureCase(TypedDict, total=False):
    id: str
    candidate_id: str
    review_cycle: str
    target_rank: str
    seeking_tenure: bool
    clock_policy: str
    waiver_signed: bool
    created_by_user_id: str
    stage: str
    dossier_submitted_at: Optional[str]
    extension_days: int
    mandatory_review_date: str
    dossier_strength_index: Optional[float]
    recommendation_score: Optional[float]
    appeal_filing_deadline: Optional[str]
    closed_at: Optional[str]
    retention_until: Optional[str]
    purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DossierItem(TypedDict, total=False):
    id: str
    case_id: str
    category: str
    title: str
    page_count: int
    is_peer_reviewed: bool
    supersedes_item_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExternalReviewer(TypedDict, total=False):
    id: str
    full_name: str
    institution: str
    email: str
    expertise_area: str
    created_at: str
    updated_at: str
    version: int


class ReviewerInvitation(TypedDict, total=False):
    id: str
    case_id: str
    reviewer_id: str
    invited_at: str
    response_deadline: str
    review_window_start: str
    review_window_end: str
    is_arm_length: bool
    declared_coauthor: bool
    letter_received_at: Optional[str]
    letter_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict, total=False):
    id: str
    level: str
    academic_unit: str
    term_start: str
    term_end: str
    quorum_fraction: float
    pass_rule: str
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict, total=False):
    id: str
    committee_id: str
    full_name: str
    email: str
    role_in_committee: str
    service_start: str
    service_end: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class ReviewRound(TypedDict, total=False):
    id: str
    case_id: str
    committee_id: str
    level: str
    opened_at: Optional[str]
    status: str
    active_member_count: Optional[int]
    recusal_count: int
    eligible_voter_count: Optional[int]
    quorum_required: Optional[int]
    votes_cast: int
    yes_count: int
    no_count: int
    abstain_count: int
    quorum_met: bool
    yes_percentage: Optional[float]
    passed: Optional[bool]
    recommendation: Optional[str]
    letter_text: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vote(TypedDict, total=False):
    id: str
    round_id: str
    member_id: str
    ballot: str
    status: str
    cast_at: str
    retracted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClockExtensionRequest(TypedDict, total=False):
    id: str
    case_id: str
    reason: str
    interval_start: str
    interval_end: str
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MidTenureReview(TypedDict, total=False):
    id: str
    case_id: str
    review_year: int
    outcome: Optional[str]
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProvostDecision(TypedDict, total=False):
    id: str
    case_id: str
    decision: str
    rationale_text: str
    override_rationale: Optional[str]
    recorded_by_user_id: str
    decided_at: str
    notification_deadline: str
    notification_sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    case_id: str
    grounds: str
    filed_at: str
    status: str
    resolution: Optional[str]
    resolution_text: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
