"""Domain types: entity TypedDicts, status enums, role enum.

All resources in this API carry the standard system-managed fields
(id, created_at, updated_at, version) per the PRD's common-resource rules.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    LIAISON_OFFICER = "LiaisonOfficer"
    BLOCK_CAPTAIN = "BlockCaptain"
    MEMBER = "Member"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class Posture(str, Enum):
    DORMANT = "DORMANT"
    FORMATION = "FORMATION"
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    FROZEN = "FROZEN"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    DEREGISTERED = "DEREGISTERED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class ContactChannel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"
    PHONE_TREE = "PHONE_TREE"


class RosterVisibility(str, Enum):
    GROUP_ONLY = "GROUP_ONLY"
    LIAISON_VISIBLE = "LIAISON_VISIBLE"
    PROGRAM_WIDE = "PROGRAM_WIDE"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELIEVED = "RELIEVED"
    REVOKED = "REVOKED"


class IncidentCategory(str, Enum):
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    PROPERTY_CRIME = "PROPERTY_CRIME"
    VANDALISM = "VANDALISM"
    NOISE = "NOISE"
    TRAFFIC = "TRAFFIC"
    OTHER = "OTHER"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    CORROBORATED = "CORROBORATED"
    DISMISSED = "DISMISSED"
    CLEARED = "CLEARED"


class AlertKind(str, Enum):
    INCIDENT_BULLETIN = "INCIDENT_BULLETIN"
    MEETING_NOTICE = "MEETING_NOTICE"
    EVENT_NOTICE = "EVENT_NOTICE"
    SAFETY_TIP = "SAFETY_TIP"


class AudienceScope(str, Enum):
    BLOCK = "BLOCK"
    GROUP = "GROUP"


class DistributionStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    SENT = "SENT"
    RECALLED = "RECALLED"


class AckPosture(str, Enum):
    UNTRACKED = "UNTRACKED"
    PARTIAL = "PARTIAL"
    MAJORITY = "MAJORITY"
    FULL = "FULL"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class AgreementScope(str, Enum):
    INCIDENT_SUMMARIES = "INCIDENT_SUMMARIES"
    ROSTER_CONTACTS = "ROSTER_CONTACTS"
    FULL = "FULL"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Curriculum(str, Enum):
    BIAS_AVOIDANCE = "BIAS_AVOIDANCE"
    OBSERVATION_SKILLS = "OBSERVATION_SKILLS"
    REPORT_WRITING = "REPORT_WRITING"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventKind(str, Enum):
    NATIONAL_NIGHT_OUT = "NATIONAL_NIGHT_OUT"
    BLOCK_PARTY = "BLOCK_PARTY"
    SAFETY_FAIR = "SAFETY_FAIR"


class EventStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewDecisionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONDITIONAL = "CONDITIONAL"


class WatchGroup(TypedDict, total=False):
    id: str
    name: str
    precinct_code: str
    certification_status: str
    certification_valid_until: Optional[str]
    posture: str
    sign_inventory_count: int
    materials_inventory_count: int
    participation_score: float
    training_cooldown_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Block(TypedDict, total=False):
    id: str
    watch_group_id: str
    street_segment: str
    household_count: int
    registration_status: str
    risk_heat_score: float
    last_incident_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    watch_group_id: str
    block_id: str
    full_name: str
    contact_channel: str
    roster_visibility: str
    membership_status: str
    bias_training_completed_at: Optional[str]
    strike_count: int
    created_at: str
    updated_at: str
    version: int


class BlockCaptainAssignment(TypedDict, total=False):
    id: str
    block_id: str
    member_id: str
    assignment_status: str
    assigned_at: str
    relieved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    block_id: str
    reporter_member_id: str
    category: str
    occurred_at: str
    severity: int
    review_status: str
    corroboration_weight: float
    shared_with_liaison: bool
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    watch_group_id: str
    origin_incident_id: Optional[str]
    alert_kind: str
    audience_scope: str
    target_block_id: Optional[str]
    distribution_status: str
    ack_posture: str
    scheduled_send_at: str
    recipient_count: int
    ack_count: int
    created_at: str
    updated_at: str
    version: int


class LiaisonMeeting(TypedDict, total=False):
    id: str
    watch_group_id: str
    liaison_officer_id: str
    room_slot_start: str
    room_slot_end: str
    meeting_status: str
    quorum_met: bool
    attendee_count: int
    created_at: str
    updated_at: str
    version: int


class LiaisonOfficer(TypedDict, total=False):
    id: str
    badge_number: str
    full_name: str
    precinct_code: str
    created_at: str
    updated_at: str
    version: int


class DataShareAgreement(TypedDict, total=False):
    id: str
    watch_group_id: str
    liaison_officer_id: str
    scope: str
    agreement_status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    watch_group_id: str
    trainer_officer_id: str
    curriculum: str
    scheduled_at: str
    session_status: str
    attending_member_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class CommunityEvent(TypedDict, total=False):
    id: str
    watch_group_id: str
    event_kind: str
    street_closure_start: str
    street_closure_end: str
    event_status: str
    estimated_attendance: int
    created_at: str
    updated_at: str
    version: int


class CertificationReview(TypedDict, total=False):
    id: str
    watch_group_id: str
    reviewing_officer_id: str
    review_status: str
    certification_points: float
    certification_grant_months: int
    created_at: str
    updated_at: str
    version: int
