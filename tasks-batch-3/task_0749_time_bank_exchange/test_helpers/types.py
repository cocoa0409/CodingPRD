"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    PROJECT_ORGANIZER = "ProjectOrganizer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class TrustTier(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    BASIC = "BASIC"
    TRUSTED = "TRUSTED"
    ANCHOR = "ANCHOR"


class SkillOfferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class SkillRequestStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class ExchangeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RedemptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    VOIDED = "VOIDED"


class VerificationCredentialStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CredentialType(str, Enum):
    ID_CHECK = "ID_CHECK"
    SKILL_ATTEST = "SKILL_ATTEST"
    REFERENCE_ATTEST = "REFERENCE_ATTEST"


class GroupProjectState(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProjectShiftStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShiftAssignmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    WITHDRAWN = "WITHDRAWN"


class DisputeReasonCode(str, Enum):
    NO_SHOW = "NO_SHOW"
    INCOMPLETE_SERVICE = "INCOMPLETE_SERVICE"
    WRONG_DURATION = "WRONG_DURATION"
    OTHER = "OTHER"


class LedgerEntryKind(str, Enum):
    EARNED = "EARNED"
    SPENT = "SPENT"
    REDEMPTION = "REDEMPTION"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
    DISPUTE_REVERSAL = "DISPUTE_REVERSAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

# common_fields: true — carries id + created_at + updated_at + version
class Member(TypedDict):
    id: str
    email: str
    display_name: str
    home_neighborhood: str
    trust_tier: str
    verified_credential_count: int
    completed_exchange_count: int
    chronological_balance_minutes: int
    forward_looking_balance_minutes: int
    lifetime_earned_minutes: int
    lifetime_redeemed_minutes: int
    no_show_strikes: int
    is_suspended: bool
    created_at: str
    updated_at: str
    version: int


class SkillOffer(TypedDict):
    id: str
    member_id: str
    skill_code: str
    title: str
    minutes_per_session: int
    required_trust_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SkillRequest(TypedDict):
    id: str
    member_id: str
    skill_code: str
    needed_minutes: int
    earliest_start_utc: str
    latest_start_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Exchange(TypedDict):
    id: str
    offer_id: str
    request_id: str
    provider_member_id: str
    requester_member_id: str
    scheduled_start_utc: str
    committed_minutes: int
    status: str
    settled_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, only id + created_at
class LedgerEntry(TypedDict):
    id: str
    member_id: str
    exchange_id: Optional[str]
    redemption_id: Optional[str]
    entry_kind: str
    delta_minutes: int
    posted_at: str
    memo: Optional[str]
    created_at: str


class Redemption(TypedDict):
    id: str
    member_id: str
    reward_code: str
    minutes_cost: int
    status: str
    fulfilled_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationCredential(TypedDict):
    id: str
    subject_member_id: str
    verifier_member_id: Optional[str]
    credential_type: str
    skill_code: Optional[str]
    evidence_url: str
    status: str
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class GroupProject(TypedDict):
    id: str
    organizer_member_id: str
    title: str
    window_start_utc: str
    window_end_utc: str
    minimum_completed_ratio: float
    aggregate_state: str
    total_committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class ProjectShift(TypedDict):
    id: str
    project_id: str
    role_label: str
    shift_start_utc: str
    duration_minutes: int
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict):
    id: str
    shift_id: str
    member_id: str
    status: str
    check_in_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    exchange_id: str
    raised_by_member_id: str
    reason_code: str
    claimed_delta_minutes: int
    status: str
    admin_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImpactReport(TypedDict):
    id: str
    report_month: str
    total_hours_exchanged: float
    unique_active_members: int
    top_skill_code: Optional[str]
    generated_by_user_id: str
    created_at: str
    updated_at: str
    version: int
