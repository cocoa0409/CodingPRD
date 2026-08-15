"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CALLER = "Caller"
    COUNSELOR = "Counselor"
    HOTLINE_SUPERVISOR = "HotlineSupervisor"
    DATA_PROTECTION_OFFICER = "DataProtectionOfficer"
    AGENCY_ADMIN = "AgencyAdmin"
    ANALYST = "Analyst"


# ---------------------------------------------------------------------------
# Status / field enums (PRD §3)
# ---------------------------------------------------------------------------
class JurisdictionLevel(str, Enum):
    STATE = "STATE"
    COUNTY = "COUNTY"
    CITY = "CITY"


class IssueCategory(str, Enum):
    EVICTION = "EVICTION"
    HABITABILITY = "HABITABILITY"
    DEPOSIT = "DEPOSIT"


class ScriptStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ResourceStatus(str, Enum):
    CURRENT = "CURRENT"
    OUTDATED = "OUTDATED"
    RETIRED = "RETIRED"


class CounselorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class CallerChannel(str, Enum):
    PHONE = "PHONE"
    CHAT = "CHAT"
    TTY = "TTY"
    VIDEO = "VIDEO"


class ConsentType(str, Enum):
    RECORDING = "RECORDING"
    FOLLOW_UP = "FOLLOW_UP"
    LEGAL_AID_RELEASE = "LEGAL_AID_RELEASE"
    DATA_SHARING = "DATA_SHARING"


class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SessionStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    ACTIVE = "ACTIVE"
    WRAPPED_UP = "WRAPPED_UP"
    DROPPED = "DROPPED"
    ABANDONED = "ABANDONED"


class InterpretationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUESTED = "REQUESTED"
    CONNECTED = "CONNECTED"
    FAILED = "FAILED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_FOLLOW_UP = "PENDING_FOLLOW_UP"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ScoreVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    VERIFIED = "VERIFIED"


class UrgencyTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class ReferralType(str, Enum):
    LEGAL_AID = "LEGAL_AID"
    SELF_HELP = "SELF_HELP"


class ReferralStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    OPERATOR = "OPERATOR"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    CONSENT_EXPIRED = "CONSENT_EXPIRED"
    SCRIPT_OUTDATED = "SCRIPT_OUTDATED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PurgeJobStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    BLOCKED_BY_HOLD = "BLOCKED_BY_HOLD"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Jurisdiction(TypedDict, total=False):
    id: str
    parent_jurisdiction_id: Optional[str]
    code: str
    name: str
    level: str
    eviction_notice_days: int
    habitability_repair_days: int
    deposit_cap_months: float
    deposit_interest_required: bool
    deposit_interest_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class RightsScript(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    issue_category: str
    version_no: int
    body: str
    effective_from: Optional[str]
    effective_until: Optional[str]
    supersedes_script_id: Optional[str]
    author_counselor_id: str
    reviewer_counselor_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SelfHelpResource(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    issue_category: str
    title: str
    body: str
    language_code: str
    linked_script_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict, total=False):
    id: str
    display_name: str
    languages: List[str]
    certified_jurisdiction_codes: List[str]
    certified_categories: List[str]
    certification_expires_at: str
    is_script_reviewer: bool
    trained_script_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Interpreter(TypedDict, total=False):
    id: str
    display_name: str
    language_code: str
    created_at: str
    updated_at: str
    version: int


class Caller(TypedDict, total=False):
    id: str
    alias: str
    phone: Optional[str]
    preferred_language: str
    channel: str
    accessibility_needs: List[str]
    is_anonymous: bool
    pii_purged: bool
    do_not_aggregate: bool
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    caller_id: str
    consent_type: str
    status: str
    granted_at: str
    expires_at: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CallSession(TypedDict, total=False):
    id: str
    caller_id: str
    jurisdiction_id: str
    issue_category: str
    triage_notes: Optional[str]
    counselor_id: Optional[str]
    interpreter_id: Optional[str]
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    queue_wait_seconds: int
    session_status: str
    interpretation_status: str
    pinned_script_id: Optional[str]
    failed_interpreter_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    caller_id: str
    opened_from_session_id: str
    jurisdiction_id: str
    issue_category: str
    opened_by_counselor_id: str
    eviction_notice_date: Optional[str]
    notice_served_at: Optional[str]
    habitability_reported_at: Optional[str]
    deposit_amount_cents: Optional[int]
    monthly_rent_cents: Optional[int]
    deposit_days_held: Optional[int]
    legal_hold: bool
    priority_score: int
    urgency_tier: str
    score_variant: str
    verified_by_counselor_id: Optional[str]
    missed_follow_up_count: int
    required_follow_up_count: int
    escalation_level: int
    last_escalated_at: Optional[str]
    deposit_exposure_cents: Optional[int]
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CaseNote(TypedDict, total=False):
    """Append-only note log: carries ONLY id + created_at from the common set
    (PRD §2.4) — no updated_at, no version, no update or delete endpoint."""
    id: str
    created_at: str
    case_id: str
    counselor_id: Optional[str]
    body: str
    is_confidential: bool
    system_generated: bool


class FollowUp(TypedDict, total=False):
    id: str
    case_id: str
    scheduled_for: str
    status: str
    completed_at: Optional[str]
    outcome: Optional[str]
    auto_created: bool
    required_count_at_schedule: int
    created_at: str
    updated_at: str
    version: int


class LegalAidOrg(TypedDict, total=False):
    id: str
    name: str
    covered_jurisdiction_codes: List[str]
    accepted_categories: List[str]
    weekly_capacity: int
    current_week_reserved: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    case_id: str
    referral_type: str
    legal_aid_org_id: Optional[str]
    self_help_resource_id: Optional[str]
    status: str
    sla_dispatch_by: str
    accept_by: Optional[str]
    dispatched_at: Optional[str]
    declined_org_ids: List[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionPolicy(TypedDict, total=False):
    id: str
    jurisdiction_id: Optional[str]
    issue_category: Optional[str]
    retention_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurgeJob(TypedDict, total=False):
    id: str
    caller_id: str
    status: str
    created_by_sweep: bool
    executed_at: Optional[str]
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
