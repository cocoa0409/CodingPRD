"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PRINCIPAL_INVESTIGATOR = "PrincipalInvestigator"
    REVIEWER = "Reviewer"
    IRB_CHAIR = "IrbChair"
    IRB_COORDINATOR = "IrbCoordinator"
    IRB_ADMIN = "IrbAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class InvestigatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEBARRED = "DEBARRED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MemberCategory(str, Enum):
    SCIENTIST = "SCIENTIST"
    NON_SCIENTIST = "NON_SCIENTIST"
    UNAFFILIATED = "UNAFFILIATED"
    PRISONER_REPRESENTATIVE = "PRISONER_REPRESENTATIVE"


class ReviewLevel(str, Enum):
    EXEMPT = "EXEMPT"
    EXPEDITED = "EXPEDITED"
    FULL_BOARD = "FULL_BOARD"


class RiskLevel(str, Enum):
    MINIMAL = "MINIMAL"
    GREATER_THAN_MINIMAL = "GREATER_THAN_MINIMAL"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    UNDER_EXPEDITED_REVIEW = "UNDER_EXPEDITED_REVIEW"
    AWAITING_FULL_BOARD = "AWAITING_FULL_BOARD"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    BOARD_CHANGES_REQUESTED = "BOARD_CHANGES_REQUESTED"
    EXEMPT_ACTIVE = "EXEMPT_ACTIVE"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    DISAPPROVED = "DISAPPROVED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class ConsentDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"


class WaiverType(str, Enum):
    NONE = "NONE"
    WAIVER_OF_CONSENT = "WAIVER_OF_CONSENT"
    WAIVER_OF_DOCUMENTATION = "WAIVER_OF_DOCUMENTATION"
    ALTERATION_OF_CONSENT = "ALTERATION_OF_CONSENT"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RECUSED = "RECUSED"
    EXPIRED = "EXPIRED"
    SUBMITTED = "SUBMITTED"


class ReviewerRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    MINOR_REVISIONS = "MINOR_REVISIONS"
    MAJOR_REVISIONS = "MAJOR_REVISIONS"
    DISAPPROVE = "DISAPPROVE"


class DeclarationType(str, Enum):
    NONE = "NONE"
    FINANCIAL = "FINANCIAL"
    PERSONAL = "PERSONAL"
    SCIENTIFIC = "SCIENTIFIC"


class DeclarationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    CONFLICTED = "CONFLICTED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONVENED = "CONVENED"
    ADJOURNED = "ADJOURNED"
    CANCELLED = "CANCELLED"
    FAILED_QUORUM = "FAILED_QUORUM"


class AgendaItemStatus(str, Enum):
    LISTED = "LISTED"
    VOTED = "VOTED"
    DEFERRED = "DEFERRED"
    REMOVED = "REMOVED"


class PriorityClass(str, Enum):
    SUSPENSION_REVIEW = "SUSPENSION_REVIEW"
    INITIAL_REVIEW = "INITIAL_REVIEW"
    MODIFICATION = "MODIFICATION"


class VoteOutcome(str, Enum):
    APPROVE = "APPROVE"
    DISAPPROVE = "DISAPPROVE"
    REQUIRE_CHANGES = "REQUIRE_CHANGES"
    DEFER = "DEFER"


class ModificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ModificationScope(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class ContinuingReviewStatus(str, Enum):
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    LAPSED = "LAPSED"


class AdverseEventType(str, Enum):
    SERIOUS_ADVERSE_EVENT = "SERIOUS_ADVERSE_EVENT"
    UNANTICIPATED_PROBLEM = "UNANTICIPATED_PROBLEM"
    PROTOCOL_DEVIATION_WITH_HARM = "PROTOCOL_DEVIATION_WITH_HARM"


class AdverseEventStatus(str, Enum):
    FILED = "FILED"
    TRIAGED = "TRIAGED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    CLOSED_WITH_ACTION = "CLOSED_WITH_ACTION"


class CaseSource(str, Enum):
    LATE_AE = "LATE_AE"
    LAPSED_CR = "LAPSED_CR"
    AE_ACTION = "AE_ACTION"
    MANUAL = "MANUAL"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    INVESTIGATION = "INVESTIGATION"
    FINDING_CONFIRMED = "FINDING_CONFIRMED"
    FINDING_NOT_CONFIRMED = "FINDING_NOT_CONFIRMED"
    CLOSED = "CLOSED"


class RelianceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


# All resources carry the four common system-managed properties of PRD §2.5:
# id, created_at, updated_at, version.

class Investigator(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    department: str
    training_expires_at: str
    provisional_compliance_score: int
    final_compliance_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IrbMember(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    member_category: str
    is_chair: bool
    status: str
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Protocol(TypedDict, total=False):
    id: str
    pi_id: str
    title: str
    claimed_review_level: str
    risk_level: str
    involves_prisoners: bool
    is_industry_sponsored: bool
    determined_review_level: Optional[str]
    provisional_fee_cents: int
    settled_fee_cents: Optional[int]
    fee_delta_cents: Optional[int]
    approval_expires_at: Optional[str]
    continuing_review_interval_days: Optional[int]
    pre_suspension_state: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentDocument(TypedDict, total=False):
    id: str
    protocol_id: str
    version_seq: int
    file_ref: str
    waiver_type: str
    waiver_criterion_minimal_risk: bool
    waiver_criterion_rights_not_adversely_affected: bool
    waiver_criterion_impracticable_without_waiver: bool
    waiver_criterion_debrief_when_appropriate: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewAssignment(TypedDict, total=False):
    id: str
    protocol_id: str
    reviewer_id: str
    reviewer_role: str
    offered_at: str
    response_deadline_at: str
    recommendation: Optional[str]
    recommendation_voided: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConflictDeclaration(TypedDict, total=False):
    id: str
    protocol_id: str
    reviewer_id: str
    declaration_type: str
    detail: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardMeeting(TypedDict, total=False):
    id: str
    room_id: str
    scheduled_at: str
    duration_minutes: int
    attendee_member_ids: List[str]
    quorum_threshold: Optional[int]
    item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AgendaItem(TypedDict, total=False):
    id: str
    meeting_id: str
    protocol_id: str
    modification_id: Optional[str]
    priority_class: str
    votes_for: Optional[int]
    votes_against: Optional[int]
    votes_abstain: Optional[int]
    eligible_voter_count: Optional[int]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ModificationRequest(TypedDict, total=False):
    id: str
    protocol_id: str
    scope: str
    description: str
    new_consent_document_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContinuingReview(TypedDict, total=False):
    id: str
    protocol_id: str
    cycle_index: int
    due_at: str
    window_opens_at: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseEventReport(TypedDict, total=False):
    id: str
    protocol_id: str
    event_type: str
    occurred_at: str
    description: str
    reported_at: str
    deadline_at: str
    is_late: bool
    triage_note: Optional[str]
    action_type: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NonComplianceCase(TypedDict, total=False):
    id: str
    protocol_id: str
    source: str
    reason: Optional[str]
    opened_at: str
    finding_confirmed: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class RelianceAgreement(TypedDict, total=False):
    id: str
    protocol_id: str
    ceding_institution_code: str
    reviewing_institution_code: str
    effective_start_date: str
    effective_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
