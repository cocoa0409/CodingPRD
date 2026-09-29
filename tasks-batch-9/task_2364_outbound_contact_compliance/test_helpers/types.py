"""Typed shapes for the Outbound Contact Compliance API.

Every entity carries the four common fields declared by the PRD: ``id``,
``created_at``, ``updated_at`` and ``version``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole:
    """Role strings accepted in the ``X-User-Role`` header."""

    CAMPAIGN_MANAGER = "CampaignManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DIALER_OPERATOR = "DialerOperator"
    PLATFORM_ADMIN = "PlatformAdmin"
    CONSUMER = "Consumer"


ALL_ROLES = [
    UserRole.CAMPAIGN_MANAGER,
    UserRole.COMPLIANCE_OFFICER,
    UserRole.DIALER_OPERATOR,
    UserRole.PLATFORM_ADMIN,
    UserRole.CONSUMER,
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Channel:
    VOICE = "VOICE"
    SMS = "SMS"


class PhoneType:
    WIRELESS = "WIRELESS"
    LANDLINE = "LANDLINE"
    UNKNOWN = "UNKNOWN"


class InternalDncStatus:
    CLEAR = "CLEAR"
    SUPPRESSED = "SUPPRESSED"


class RiskTier:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RndResult:
    NOT_CHECKED = "NOT_CHECKED"
    NO_MATCH = "NO_MATCH"
    REASSIGNED = "REASSIGNED"
    NO_DATA = "NO_DATA"


class ConsentType:
    EXPRESS_WRITTEN = "EXPRESS_WRITTEN"
    EXPRESS_ORAL = "EXPRESS_ORAL"
    ESTABLISHED_BUSINESS_RELATIONSHIP = "ESTABLISHED_BUSINESS_RELATIONSHIP"


class CaptureMethod:
    WEB_FORM = "WEB_FORM"
    PAPER_FORM = "PAPER_FORM"
    IVR_RECORDING = "IVR_RECORDING"
    SMS_DOUBLE_OPT_IN = "SMS_DOUBLE_OPT_IN"
    AGENT_ATTESTATION = "AGENT_ATTESTATION"


class ConsentStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class RevocationChannelReceived:
    VOICE = "VOICE"
    SMS = "SMS"
    EMAIL = "EMAIL"
    WEB = "WEB"
    MAIL = "MAIL"


class RevocationMethod:
    REPLY_STOP = "REPLY_STOP"
    VERBAL_REQUEST = "VERBAL_REQUEST"
    EMAIL_REQUEST = "EMAIL_REQUEST"
    WEB_PORTAL = "WEB_PORTAL"
    POSTAL_MAIL = "POSTAL_MAIL"


class RevocationScope:
    ALL_CHANNELS = "ALL_CHANNELS"
    VOICE = "VOICE"
    SMS = "SMS"


class IntakeStatus:
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class PropagationStatus:
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PROPAGATED = "PROPAGATED"
    OVERDUE = "OVERDUE"


class RejectionReason:
    NOT_CONSUMER = "NOT_CONSUMER"
    UNVERIFIABLE_IDENTITY = "UNVERIFIABLE_IDENTITY"
    DUPLICATE = "DUPLICATE"


class ListType:
    NATIONAL = "NATIONAL"
    STATE = "STATE"
    INTERNAL = "INTERNAL"


class SuppressionSource:
    FTC_DNC_DOWNLOAD = "FTC_DNC_DOWNLOAD"
    STATE_REGISTRY = "STATE_REGISTRY"
    CONSUMER_REQUEST = "CONSUMER_REQUEST"
    LITIGATION_HOLD = "LITIGATION_HOLD"


class SuppressionStatus:
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class RemovalReason:
    CONSENT_REINSTATED = "CONSENT_REINSTATED"
    REGISTRY_DELISTING = "REGISTRY_DELISTING"
    DATA_ERROR = "DATA_ERROR"


class ScrubJobStatus:
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class ScrubFailureReason:
    STALE_OR_EMPTY_LIST = "STALE_OR_EMPTY_LIST"


class ScrubInvalidationReason:
    NEW_INTERNAL_SUPPRESSION = "NEW_INTERNAL_SUPPRESSION"


class CampaignPurpose:
    MARKETING = "MARKETING"
    INFORMATIONAL = "INFORMATIONAL"
    DEBT_COLLECTION = "DEBT_COLLECTION"


class CampaignStatus:
    DRAFT = "DRAFT"
    PENDING_LAUNCH = "PENDING_LAUNCH"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SuspensionReason:
    MANUAL = "MANUAL"
    ABANDONMENT_BREACH = "ABANDONMENT_BREACH"
    SCRUB_STALE = "SCRUB_STALE"
    EMERGENCY_RESTRICTION = "EMERGENCY_RESTRICTION"
    PROFILE_LOCKED = "PROFILE_LOCKED"


class DialerMode:
    PREVIEW = "PREVIEW"
    POWER = "POWER"
    PREDICTIVE = "PREDICTIVE"


class DialerProfileStatus:
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class DialerLockedReason:
    ABANDONMENT_BREACH = "ABANDONMENT_BREACH"


class DisclosureBlockType:
    IDENTIFICATION = "IDENTIFICATION"
    PURPOSE = "PURPOSE"
    OPT_OUT = "OPT_OUT"
    RECORDING_NOTICE = "RECORDING_NOTICE"


class RecordingConsentMode:
    ONE_PARTY = "ONE_PARTY"
    ALL_PARTY = "ALL_PARTY"


class AgentScriptStatus:
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"


class RecordingConsentRegime:
    ONE_PARTY = "ONE_PARTY"
    ALL_PARTY = "ALL_PARTY"


class PolicyStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EmergencyStatus:
    NONE = "NONE"
    ACTIVE = "ACTIVE"


class AttemptOutcome:
    PENDING = "PENDING"
    CONNECTED_LIVE = "CONNECTED_LIVE"
    ABANDONED = "ABANDONED"
    MACHINE_ANSWERED = "MACHINE_ANSWERED"
    NO_ANSWER = "NO_ANSWER"
    VOIDED = "VOIDED"


class VoidReason:
    MISDIAL = "MISDIAL"
    CAMPAIGN_SUSPENDED = "CAMPAIGN_SUSPENDED"
    COMPLIANCE_CORRECTION = "COMPLIANCE_CORRECTION"


class ComplaintSource:
    DIRECT = "DIRECT"
    STATE_AG = "STATE_AG"
    FTC = "FTC"
    LITIGATION = "LITIGATION"


class AllegedViolationType:
    NO_CONSENT = "NO_CONSENT"
    DNC_VIOLATION = "DNC_VIOLATION"
    TIME_WINDOW = "TIME_WINDOW"
    ABANDONMENT = "ABANDONMENT"
    RECORDING_CONSENT = "RECORDING_CONSENT"


class ComplaintStatus:
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Contact(CommonFields, total=False):
    phone_number: str
    state_code: str
    utc_offset_minutes: int
    time_zone_label: str
    phone_type: str
    attempt_budget_total: int
    attempts_charged: int
    attempt_budget_remaining: int
    internal_dnc_status: str
    risk_tier: str
    active_consent_count: int
    suspended_consent_count: int
    revoked_consent_count: int
    superseded_consent_count: int
    total_consent_count: int
    rnd_result: str
    rnd_checked_at: Optional[str]
    rnd_claimed_consent_date: Optional[str]
    rnd_safe_harbor_eligible: bool
    overdue_propagation_count: int


class ConsentRecord(CommonFields, total=False):
    contact_id: str
    channel: str
    consent_type: str
    capture_method: str
    disclosure_script_id: str
    disclosure_text_version: int
    signature_evidence: str
    captured_at: str
    status: str
    suspended_reason: Optional[str]
    revoked_at: Optional[str]
    reinstatement_count: int


class RevocationRequest(CommonFields, total=False):
    contact_id: str
    channel_received: str
    method: str
    scope: str
    received_note: str
    received_at: str
    intake_status: str
    propagation_status: str
    propagation_deadline_at: Optional[str]
    validated_at: Optional[str]
    propagated_at: Optional[str]
    consent_records_revoked_count: int
    rejection_reason: Optional[str]
    target_systems: List[str]


class SuppressionEntry(CommonFields, total=False):
    list_type: str
    phone_number: str
    state_code: Optional[str]
    source: str
    source_refreshed_at: str
    status: str
    removed_at: Optional[str]
    removal_reason: Optional[str]


class ScrubJob(CommonFields, total=False):
    campaign_id: str
    list_types: List[str]
    status: str
    requested_at: str
    completed_at: Optional[str]
    expires_at: Optional[str]
    contacts_scrubbed_count: int
    contacts_suppressed_count: int
    eligible_target_count: int
    failure_reason: Optional[str]
    invalidation_reason: Optional[str]


class Campaign(CommonFields, total=False):
    name: str
    channel: str
    campaign_purpose: str
    target_state_codes: List[str]
    dialer_profile_id: str
    agent_script_id: str
    status: str
    suspension_reason: Optional[str]
    launch_certified_by_user_id: Optional[str]
    pinned_script_version: Optional[int]
    latest_scrub_status: Optional[str]
    eligible_target_count: int
    measurement_date: Optional[str]
    live_answer_count_today: int
    abandoned_count_today: int
    machine_count_today: int
    no_answer_count_today: int
    regulatory_abandonment_rate_pct: float
    internal_abandonment_rate_pct: float
    daily_rate_history: List[Dict[str, Any]]
    rolling_compliance_rate_pct: float
    permitted_attempt_count: int
    voided_attempt_count: int


class DialerProfile(CommonFields, total=False):
    mode: str
    abandonment_limit_pct: float
    amd_enabled: bool
    amd_abandon_on_machine: bool
    abandon_message_seconds: int
    agents_available: int
    requires_waiver: bool
    waiver_reference: Optional[str]
    max_lines_last_computed: Optional[int]
    status: str
    locked_reason: Optional[str]
    approved_by_user_id: Optional[str]


class DisclosureBlock(TypedDict, total=False):
    block_type: str
    text: str


class AgentScript(CommonFields, total=False):
    name: str
    channel: str
    disclosure_blocks: List[DisclosureBlock]
    recording_consent_mode: str
    covered_state_codes: List[str]
    status: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    change_note: Optional[str]
    review_cycle_count: int


class CallingWindowPolicy(CommonFields, total=False):
    state_code: str
    window_start_local: str
    window_end_local: str
    window_start_minutes: int
    window_end_minutes: int
    holiday_dates: List[str]
    recording_consent_regime: str
    effective_from: str
    effective_to: str
    supersedes_policy_id: Optional[str]
    status: str
    emergency_status: str
    emergency_declared_at: Optional[str]
    emergency_note: Optional[str]


class ContactAttempt(CommonFields, total=False):
    campaign_id: str
    contact_id: str
    channel: str
    consent_record_id: Optional[str]
    calling_window_policy_id: Optional[str]
    requested_at: str
    recipient_local_minutes: int
    recipient_local_time: str
    effective_window_start_minutes: int
    effective_window_end_minutes: int
    cooldown_until: Optional[str]
    max_lines_snapshot: Optional[int]
    outcome: str
    agent_connect_seconds: Optional[int]
    abandon_message_played: Optional[bool]
    outcome_recorded_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]


class Complaint(CommonFields, total=False):
    contact_id: str
    campaign_id: str
    source: str
    alleged_violation_type: str
    narrative: str
    litigation_flag: bool
    received_at: str
    status: str
    provisional_risk_score: float
    adjudicated_risk_score: Optional[float]
    verified_attempt_count: int
    exposure_cents: Optional[int]
    willful: Optional[bool]
    finding_note: Optional[str]
    dismissal_note: Optional[str]
    pattern_cluster_size: int


Headers = Dict[str, str]
Payload = Dict[str, Any]
