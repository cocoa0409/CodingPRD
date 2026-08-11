"""Domain types: entity TypedDicts, status enums, role enum for the Board Governance API."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    CORPORATE_SECRETARY = "CorporateSecretary"
    DIRECTOR = "Director"
    BOARD_CHAIR = "BoardChair"
    EXTERNAL_AUDITOR = "ExternalAuditor"


class BylawsStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class DirectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"
    TERM_EXPIRED = "TERM_EXPIRED"


class IndependenceStatus(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    NON_INDEPENDENT = "NON_INDEPENDENT"
    PENDING_REVIEW = "PENDING_REVIEW"


class CommitteeStatus(str, Enum):
    CHARTER_DRAFT = "CHARTER_DRAFT"
    ACTIVE = "ACTIVE"
    BELOW_QUORUM = "BELOW_QUORUM"
    DISSOLVED = "DISSOLVED"


class CommitteeType(str, Enum):
    AUDIT = "AUDIT"
    COMPENSATION = "COMPENSATION"
    NOMINATING = "NOMINATING"
    SPECIAL = "SPECIAL"


class CommitteeRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class EndedReason(str, Enum):
    MANUAL = "MANUAL"
    DIRECTOR_RESIGNED = "DIRECTOR_RESIGNED"
    DIRECTOR_TERM_EXPIRED = "DIRECTOR_TERM_EXPIRED"
    COMMITTEE_DISSOLVED = "COMMITTEE_DISSOLVED"


class MeetingType(str, Enum):
    REGULAR = "REGULAR"
    SPECIAL = "SPECIAL"
    ANNUAL = "ANNUAL"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTICED = "NOTICED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"
    CANCELLED = "CANCELLED"


class MeetingNoticeStatus(str, Enum):
    SENT = "SENT"
    WAIVED = "WAIVED"


class AgendaItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INCLUDED = "INCLUDED"
    DROPPED = "DROPPED"


class BoardPackageStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    SEALED = "SEALED"
    DISTRIBUTED = "DISTRIBUTED"
    WITHDRAWN = "WITHDRAWN"


class ConfidentialityTier(str, Enum):
    GENERAL = "GENERAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class AttendanceMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    REMOTE = "REMOTE"
    PROXY = "PROXY"
    ABSENT = "ABSENT"


class ResolutionOrigin(str, Enum):
    MEETING = "MEETING"
    WRITTEN_CONSENT = "WRITTEN_CONSENT"


class ResolutionType(str, Enum):
    ORDINARY = "ORDINARY"
    SPECIAL = "SPECIAL"


class ResolutionStatus(str, Enum):
    DRAFT = "DRAFT"
    TABLED = "TABLED"
    VOTE_OPEN = "VOTE_OPEN"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    CIRCULATING = "CIRCULATING"
    CONSENT_ADOPTED = "CONSENT_ADOPTED"
    CONSENT_LAPSED = "CONSENT_LAPSED"


class VoteChannel(str, Enum):
    MEETING_BALLOT = "MEETING_BALLOT"
    WRITTEN_CONSENT = "WRITTEN_CONSENT"


class VoteValue(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"
    RECUSED = "RECUSED"


class VoteRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class DisclosureStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"


class MinutesStatus(str, Enum):
    DRAFT = "DRAFT"
    CIRCULATED_FOR_REVIEW = "CIRCULATED_FOR_REVIEW"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    ENTERED_IN_BOOK = "ENTERED_IN_BOOK"
    PURGED = "PURGED"


class AuditRequestStatus(str, Enum):
    OPEN = "OPEN"
    RECONSTRUCTING = "RECONSTRUCTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# --- Entity TypedDicts (all entities in this API carry the full common-fields
# quartet id/created_at/updated_at/version per the PRD's Common Resource Properties) ---


class Corporation(TypedDict, total=False):
    id: str
    name: str
    incorporation_state: str
    current_bylaws_id: Optional[str]
    active_director_count: int
    created_at: str
    updated_at: str
    version: int


class Bylaws(TypedDict, total=False):
    id: str
    corporation_id: str
    version_no: int
    notice_days_regular: int
    notice_days_special: int
    package_lead_days: int
    quorum_percent: int
    quorum_fixed_count: int
    consent_window_days: int
    consent_unanimity_required: bool
    minute_retention_years: int
    rotation_max_years: int
    board_seat_count: int
    status: str
    adopted_at: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Director(TypedDict, total=False):
    id: str
    corporation_id: str
    full_name: str
    email: str
    independence_status: str
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict, total=False):
    id: str
    corporation_id: str
    name: str
    committee_type: str
    charter_text: str
    quorum_fixed_count: int
    status: str
    chair_vacant: bool
    active_member_count: int
    created_at: str
    updated_at: str
    version: int


class CommitteeMembership(TypedDict, total=False):
    id: str
    committee_id: str
    director_id: str
    committee_role: str
    term_start: str
    term_end: str
    status: str
    ended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict, total=False):
    id: str
    corporation_id: str
    meeting_type: str
    scheduled_start: str
    duration_minutes: int
    location_or_medium: str
    chair_director_id: str
    status: str
    convened_at: Optional[str]
    bylaws_id_at_notice: Optional[str]
    quorum_required_count: Optional[int]
    quorum_present_snapshot: Optional[int]
    quorum_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class MeetingNotice(TypedDict, total=False):
    id: str
    meeting_id: str
    director_id: str
    sent_at: str
    required_notice_days: int
    deadline_at: str
    is_timely: bool
    status: str
    waived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgendaItem(TypedDict, total=False):
    id: str
    meeting_id: str
    title: str
    order_index: int
    proposed_by_director_id: str
    resolution_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardPackage(TypedDict, total=False):
    id: str
    meeting_id: str
    seal_count: int
    document_count: int
    status: str
    sealed_at: Optional[str]
    distributed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackageDocument(TypedDict, total=False):
    id: str
    package_id: str
    title: str
    content_ref: str
    confidentiality_tier: str
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    meeting_id: str
    director_id: str
    attendance_mode: str
    proxy_holder_director_id: Optional[str]
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class Resolution(TypedDict, total=False):
    id: str
    corporation_id: str
    meeting_id: Optional[str]
    origin: str
    resolution_type: str
    title: str
    text: str
    related_party: Optional[str]
    status: str
    consent_deadline_at: Optional[str]
    consent_required_count: Optional[int]
    consent_bylaws_id: Optional[str]
    for_count: int
    against_count: int
    abstain_count: int
    recused_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VoteRecord(TypedDict, total=False):
    id: str
    resolution_id: str
    director_id: str
    channel: str
    vote: str
    status: str
    cast_at: str
    recast_count: int
    created_at: str
    updated_at: str
    version: int


class ConflictDisclosure(TypedDict, total=False):
    id: str
    director_id: str
    corporation_id: str
    related_party: str
    effective_from: str
    effective_to: str
    description: Optional[str]
    status: str
    cleared_at: Optional[str]
    clearing_resolution_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Minutes(TypedDict, total=False):
    id: str
    meeting_id: str
    corporation_id: str
    content: str
    status: str
    review_round: int
    rejection_reason: Optional[str]
    approved_at: Optional[str]
    retention_until: Optional[str]
    book_seq_no: Optional[int]
    content_hash: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconstructionEntry(TypedDict, total=False):
    seq: int
    source_type: str
    source_id: str
    occurred_at: str


class AuditRequest(TypedDict, total=False):
    id: str
    corporation_id: str
    requested_by_label: str
    scope_start: str
    scope_end: str
    status: str
    reconstruction_digest: Optional[str]
    entry_count: Optional[int]
    governance_approval_rate_pct: Optional[float]
    failure_reason: Optional[str]
    reconstruction_log: Optional[List[ReconstructionEntry]]
    created_at: str
    updated_at: str
    version: int
