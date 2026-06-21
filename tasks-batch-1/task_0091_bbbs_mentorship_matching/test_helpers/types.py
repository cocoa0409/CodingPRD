"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes described in the PRD (§2.4, §3.1–§3.7). Append-only
activity-log entries carry only `id` and `created_at` (PRD §2.4); every other
resource additionally carries `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    BACKGROUND_SCREENER = "BackgroundScreener"
    MATCH_SPECIALIST = "MatchSpecialist"
    SUPERVISOR = "Supervisor"


# ─── Status enums ─────────────────────────────────────
class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    ELIGIBLE = "ELIGIBLE"
    MATCHED = "MATCHED"
    INACTIVE = "INACTIVE"
    SCREENING_FAILED = "SCREENING_FAILED"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class CheckType(str, Enum):
    CRIMINAL = "CRIMINAL"
    DMV = "DMV"
    CHILD_ABUSE_REGISTRY = "CHILD_ABUSE_REGISTRY"


class ChildStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    PROPOSED = "PROPOSED"
    MATCHED = "MATCHED"
    INACTIVE = "INACTIVE"


class ProposalStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class DeclineReason(str, Enum):
    VOLUNTEER_UNAVAILABLE = "VOLUNTEER_UNAVAILABLE"
    GUARDIAN_DECLINED = "GUARDIAN_DECLINED"
    POOR_FIT = "POOR_FIT"


class RelationshipStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    INTRODUCED = "INTRODUCED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ComplianceStatus(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class ClosureReason(str, Enum):
    SUCCESSFUL_CLOSURE = "SUCCESSFUL_CLOSURE"
    EARLY_TERMINATION = "EARLY_TERMINATION"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    AFFIRMED = "AFFIRMED"
    RESCINDED = "RESCINDED"


class ActivityType(str, Enum):
    OUTING = "OUTING"
    CALL = "CALL"
    MEAL = "MEAL"
    TUTORING = "TUTORING"
    EVENT = "EVENT"


class ActivityStatus(str, Enum):
    LOGGED = "LOGGED"


class ContactStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class ContactParty(str, Enum):
    BIG = "BIG"
    LITTLE = "LITTLE"
    GUARDIAN = "GUARDIAN"


class ExitType(str, Enum):
    SUCCESSFUL_CLOSURE = "SUCCESSFUL_CLOSURE"
    EARLY_TERMINATION = "EARLY_TERMINATION"


class InitiatedBy(str, Enum):
    BIG = "BIG"
    LITTLE = "LITTLE"
    GUARDIAN = "GUARDIAN"
    AGENCY = "AGENCY"


class ReasonCode(str, Enum):
    GRADUATION = "GRADUATION"
    RELOCATION = "RELOCATION"
    LOST_INTEREST = "LOST_INTEREST"
    SAFETY_CONCERN = "SAFETY_CONCERN"
    PROGRAM_VIOLATION = "PROGRAM_VIOLATION"


class ExitStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class OutcomeBand(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ───
class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    gender: str
    home_zip: str
    interest_tags: List[str]
    max_weekly_hours: int
    status: str
    active_match_count: int
    cleared_check_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    volunteer_id: str
    check_type: str
    submitted_at: str
    valid_until: Optional[str]
    adjudicated_at: Optional[str]
    adverse_findings: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict):
    id: str
    full_name: str
    email: str
    consent_on_file: bool
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    guardian_id: str
    first_name: str
    age: int
    gender: str
    home_zip: str
    interest_tags: List[str]
    requires_same_gender: bool
    status: str
    open_proposal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchProposal(TypedDict):
    id: str
    child_id: str
    volunteer_id: str
    compatibility_score: float
    candidate_pool_size: int
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    child_id: str
    volunteer_id: str
    proposal_id: str
    relationship_status: str
    compliance_status: str
    confirmed_at: str
    activated_at: Optional[str]
    last_activity_at: Optional[str]
    last_contact_at: Optional[str]
    total_mentoring_minutes: int
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchMeeting(TypedDict):
    id: str
    match_id: str
    scheduled_start: str
    scheduled_end: str
    location: str
    status: str
    outcome_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupervisionContact(TypedDict):
    id: str
    match_id: str
    due_at: str
    contacted_at: Optional[str]
    party: Optional[str]
    concern_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ExitTransition(TypedDict):
    id: str
    match_id: str
    exit_type: str
    initiated_by: str
    reason_code: str
    status: str
    survey_required: bool
    created_at: str
    updated_at: str
    version: int


class OutcomeSurvey(TypedDict):
    id: str
    match_id: str
    exit_transition_id: str
    relationship_quality: int
    child_outcome: int
    would_rematch: bool
    composite_score: float
    outcome_band: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false → id + created_at ONLY) ───
class ActivityLog(TypedDict):
    id: str
    match_id: str
    occurred_at: str
    duration_minutes: int
    activity_type: str
    status: str
    created_at: str
