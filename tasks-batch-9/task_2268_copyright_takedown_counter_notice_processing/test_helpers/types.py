"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD §2.2 (response envelope) and §2.4 (identity /
timestamps): mutable resources carry id + created_at + updated_at + version,
while the append-only safe-harbour audit record carries only id + created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class Role(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TAKEDOWN_AGENT = "TakedownAgent"
    ABUSE_INVESTIGATOR = "AbuseInvestigator"
    RIGHTS_HOLDER_REP = "RightsHolderRep"
    SUBSCRIBER = "Subscriber"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class SafeHarborStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    AT_RISK = "AT_RISK"
    FORFEITED = "FORFEITED"


class AgentRegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AccountStanding(str, Enum):
    ACTIVE = "ACTIVE"
    LIMITED = "LIMITED"
    TERMINATED = "TERMINATED"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    RESTORED = "RESTORED"
    PURGED = "PURGED"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    UNDER_NOTICE = "UNDER_NOTICE"
    COUNTER_NOTICED = "COUNTER_NOTICED"
    RESTORATION_PENDING = "RESTORATION_PENDING"
    RESOLVED = "RESOLVED"


class EnrollmentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"


class ProgramTier(str, Enum):
    STANDARD = "STANDARD"
    VERIFIED = "VERIFIED"
    TRUSTED = "TRUSTED"


class SubmissionChannel(str, Enum):
    WEB_FORM = "WEB_FORM"
    EMAIL = "EMAIL"
    API_BULK = "API_BULK"


class ComplianceVariant(str, Enum):
    SUBSTANTIAL_COMPLIANCE = "SUBSTANTIAL_COMPLIANCE"
    STRICT_COMPLIANCE = "STRICT_COMPLIANCE"


class NoticeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    PROCESSED = "PROCESSED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class ClaimStatus(str, Enum):
    MATCHED = "MATCHED"
    DISABLED = "DISABLED"
    COUNTER_NOTICED = "COUNTER_NOTICED"
    RESTORATION_SCHEDULED = "RESTORATION_SCHEDULED"
    RESTORED = "RESTORED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"


class CounterNoticeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    FORWARDED = "FORWARDED"
    RESTORATION_SCHEDULED = "RESTORATION_SCHEDULED"
    RESTORED = "RESTORED"
    BLOCKED_BY_SUIT = "BLOCKED_BY_SUIT"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECAYED = "DECAYED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class StrikeReason(str, Enum):
    NOTICE_PROCESSED = "NOTICE_PROCESSED"
    CLAIM_UPHELD = "CLAIM_UPHELD"


class TerminationStatus(str, Enum):
    OPEN = "OPEN"
    EXECUTED = "EXECUTED"
    APPEAL_FILED = "APPEAL_FILED"
    VACATED = "VACATED"
    CLOSED = "CLOSED"


class AppealDecision(str, Enum):
    UPHELD = "UPHELD"
    VACATED = "VACATED"


class MisrepresentationStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ReferenceFileStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"


class IngestionBatchStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Rejection / gate reason vocabularies (PRD §3.2, §3.5, §3.8)
# ---------------------------------------------------------------------------

NOTICE_REJECTION_SCORE_BELOW_THRESHOLD = "SCORE_BELOW_THRESHOLD"
NOTICE_REJECTION_UNSWORN_UNDER_STRICT_VARIANT = "UNSWORN_UNDER_STRICT_VARIANT"
NOTICE_REJECTION_CORE_ELEMENT_PREFIX = "CORE_ELEMENT_MISSING:"

COUNTER_REJECTION_SCORE_BELOW_THRESHOLD = "SCORE_BELOW_THRESHOLD"
COUNTER_REJECTION_CONSENT_PREFIX = "CONSENT_MISSING:"

GATE_AGENT_NOT_REGISTERED = "AGENT_NOT_REGISTERED"
GATE_POLICY_NOT_PUBLISHED = "POLICY_NOT_PUBLISHED"
GATE_CONTACT_NOT_PUBLISHED = "CONTACT_NOT_PUBLISHED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------

class MutableResource(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyResource(TypedDict):
    id: str
    created_at: str


class ServiceProviderProfile(MutableResource):
    legal_name: str
    service_domain: str
    public_contact_url: Optional[str]
    public_contact_published_at: Optional[str]
    designated_agent_registered: bool
    repeat_infringer_policy_published: bool
    safe_harbor_score: int
    safe_harbor_status: str
    last_audit_at: Optional[str]


class DesignatedAgent(MutableResource):
    provider_id: str
    agent_name: str
    agent_email: str
    agent_phone: str
    mailing_address: str
    copyright_office_receipt: Optional[str]
    registration_status: str
    submitted_at: Optional[str]
    registered_at: Optional[str]
    expires_at: Optional[str]


class RepeatInfringerPolicy(MutableResource):
    provider_id: str
    policy_text: str
    strike_expiry_days: int
    decay_step_days: int
    limitation_threshold_points: float
    termination_threshold_points: float
    appeal_window_days: int
    counter_notice_window_days: int
    dispute_window_days: int
    status: str
    published_at: Optional[str]


class Account(MutableResource):
    provider_id: str
    handle: str
    email: str
    standing: str
    strike_points: float
    upload_restricted: bool
    notified_count: int
    available_content_count: int
    terminated_at: Optional[str]


class ContentItem(MutableResource):
    account_id: str
    content_url: str
    title: str
    fingerprint_hash: str
    availability_status: str
    dispute_status: str
    disabled_at: Optional[str]
    restored_at: Optional[str]


class RightsHolder(MutableResource):
    legal_name: str
    contact_email: str
    reference_file_quota: int
    daily_item_quota: int
    enrollment_status: str
    program_tier: str
    notices_processed: int
    withdrawn_count: int
    rejected_count: int
    misrepresentation_count: int
    abuse_score: float


class TakedownNotice(MutableResource):
    rights_holder_id: str
    ingestion_batch_id: Optional[str]
    submission_channel: str
    signature_present: bool
    work_identification: Optional[str]
    material_identification: Optional[str]
    contact_email: Optional[str]
    good_faith_statement: bool
    accuracy_statement: bool
    authority_statement: bool
    sworn_under_penalty: bool
    claimed_urls: List[str]
    completeness_score: int
    compliance_variant: Optional[str]
    status: str
    rejection_reason: Optional[str]
    matched_claim_count: int
    unmatched_url_count: int
    validated_at: Optional[str]
    processed_at: Optional[str]


class NoticeClaim(MutableResource):
    notice_id: str
    content_item_id: str
    rights_holder_id: str
    reference_file_id: Optional[str]
    matched_url: str
    match_confidence: float
    status: str
    dispute_window_days: int
    counter_notice_window_days: int
    disabled_at: Optional[str]
    restoration_due_at: Optional[str]


class CounterNotice(MutableResource):
    claim_id: str
    account_id: str
    superseded_by_counter_notice_id: Optional[str]
    subscriber_name: str
    contact_email: Optional[str]
    material_identification: Optional[str]
    signature_present: bool
    good_faith_mistake_statement: bool
    consent_to_jurisdiction: bool
    consent_to_service_of_process: bool
    completeness_score: int
    status: str
    rejection_reason: Optional[str]
    forwarded_at: Optional[str]
    restoration_earliest_at: Optional[str]
    restoration_deadline_at: Optional[str]
    suit_notice_at: Optional[str]


class StrikeRecord(MutableResource):
    account_id: str
    claim_id: str
    weight: float
    base_points: float
    effective_points: float
    reason: str
    status: str
    accrued_at: str
    expires_at: Optional[str]


class TerminationCase(MutableResource):
    account_id: str
    trigger_points: float
    status: str
    opened_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    executed_at: Optional[str]
    appeal_deadline_at: Optional[str]
    appeal_filed_at: Optional[str]
    decision: Optional[str]


class MisrepresentationCase(MutableResource):
    rights_holder_id: str
    claim_id: str
    allegation: str
    opened_by_user_id: str
    substantiated_by_user_id: Optional[str]
    status: str
    affected_claim_count: int
    disabled_day_count: int
    base_penalty_cents: int
    surcharge_cents: int
    total_penalty_cents: int
    substantiated_at: Optional[str]


class ReferenceFile(MutableResource):
    rights_holder_id: str
    work_title: str
    fingerprint_hash: str
    registration_number: Optional[str]
    status: str
    activated_at: Optional[str]
    match_count: int


class IngestionBatch(MutableResource):
    rights_holder_id: str
    item_count: int
    rolling_item_total: int
    status: str
    notices_created: int
    matched_count: int
    unmatched_count: int
    accepted_at: Optional[str]


class SafeHarborAudit(AppendOnlyResource):
    provider_id: str
    median_response_hours: float
    overdue_restoration_count: int
    termination_compliance: bool
    contact_published: bool
    response_component: float
    restoration_component: float
    termination_component: float
    contact_component: float
    compliance_score: int
    resulting_status: str
    gate_failure_reason: Optional[str]


Json = Dict[str, Any]
