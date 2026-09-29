"""Domain types for the Trade Publication Circulation Audit API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CIRCULATION_MANAGER = "CirculationManager"
    QUALIFICATION_SPECIALIST = "QualificationSpecialist"
    CIRCULATION_AUDITOR = "CirculationAuditor"
    PUBLISHER_EXECUTIVE = "PublisherExecutive"
    ADVERTISER_CONTACT = "AdvertiserContact"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class PublicationFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class AuditPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class RuleDimension(str, Enum):
    JOB_FUNCTION = "JOB_FUNCTION"
    INDUSTRY = "INDUSTRY"
    PURCHASING_AUTHORITY = "PURCHASING_AUTHORITY"


class PurchasingAuthorityLevel(str, Enum):
    NONE = "NONE"
    RECOMMENDS = "RECOMMENDS"
    SPECIFIES = "SPECIFIES"
    APPROVES = "APPROVES"


class SubscriptionClass(str, Enum):
    PAID = "PAID"
    QUALIFIED_NON_PAID = "QUALIFIED_NON_PAID"
    CONTROLLED = "CONTROLLED"


class QualificationStatus(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    LAPSED = "LAPSED"
    REQUALIFICATION_REQUIRED = "REQUALIFICATION_REQUIRED"


class DeliveryStatus(str, Enum):
    DELIVERABLE = "DELIVERABLE"
    UNDELIVERABLE = "UNDELIVERABLE"
    REMOVED = "REMOVED"


class DocType(str, Enum):
    SIGNED_REQUEST_CARD = "SIGNED_REQUEST_CARD"
    WEB_FORM_CAPTURE = "WEB_FORM_CAPTURE"
    TELEPHONE_SCRIPT_LOG = "TELEPHONE_SCRIPT_LOG"
    EMAIL_CONFIRMATION = "EMAIL_CONFIRMATION"


class PurgeStatus(str, Enum):
    RETAINED = "RETAINED"
    PURGED = "PURGED"


class RequestChannel(str, Enum):
    DIRECT_MAIL = "DIRECT_MAIL"
    WEB = "WEB"
    TELEPHONE = "TELEPHONE"
    EMAIL = "EMAIL"


class QualificationRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class HygieneRunType(str, Enum):
    UNDELIVERABLE_SWEEP = "UNDELIVERABLE_SWEEP"
    EXPIRY_SWEEP = "EXPIRY_SWEEP"


class StatementBasis(str, Enum):
    AS_OF_PERIOD_END = "AS_OF_PERIOD_END"
    AUDIT_VERIFIED = "AUDIT_VERIFIED"


class StatementType(str, Enum):
    PUBLISHER_STATEMENT = "PUBLISHER_STATEMENT"
    AUDITED = "AUDITED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    UNDER_AUDIT = "UNDER_AUDIT"
    FINDINGS_OPEN = "FINDINGS_OPEN"
    AUDIT_CLEARED = "AUDIT_CLEARED"
    RESTATEMENT_REQUIRED = "RESTATEMENT_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class EngagementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIELDWORK = "FIELDWORK"
    RECONCILIATION = "RECONCILIATION"
    REPORT_ISSUED = "REPORT_ISSUED"


class FindingType(str, Enum):
    MISSING_SOURCE_DOC = "MISSING_SOURCE_DOC"
    EXPIRED_QUALIFICATION = "EXPIRED_QUALIFICATION"
    UNDELIVERABLE_NOT_REMOVED = "UNDELIVERABLE_NOT_REMOVED"
    CLASSIFICATION_ERROR = "CLASSIFICATION_ERROR"
    DIGITAL_METRIC_UNSUPPORTED = "DIGITAL_METRIC_UNSUPPORTED"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    REJECTED_REOPENED = "REJECTED_REOPENED"
    ACCEPTED_RESOLVED = "ACCEPTED_RESOLVED"


class GuaranteeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_PENDING_RESTATEMENT = "SUSPENDED_PENDING_RESTATEMENT"


class MakeGoodStatus(str, Enum):
    PENDING = "PENDING"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    WAIVED = "WAIVED"
    VOID = "VOID"


class SnapshotSource(str, Enum):
    INTERNAL_ANALYTICS = "INTERNAL_ANALYTICS"
    THIRD_PARTY_CERTIFIED = "THIRD_PARTY_CERTIFIED"


class SnapshotStatus(str, Enum):
    RECORDED = "RECORDED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class SnapshotDecision(str, Enum):
    VALIDATE = "VALIDATE"
    REJECT = "REJECT"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Publication(TypedDict):
    id: str
    name: str
    frequency: str
    industry_code: str
    qualification_validity_months: int
    renewal_grace_days: int
    source_doc_retention_months: int
    undeliverable_restrict_pct: float
    materiality_pct: float
    controlled_cap_pct: float
    audit_posture: str
    copies_on_file_total: int
    paid_copies_on_file: int
    qualified_non_paid_copies_on_file: int
    controlled_copies_on_file: int
    deliverable_copies: int
    undeliverable_copies: int
    removed_copies: int
    undeliverable_pct: float
    open_material_findings_count: int
    open_critical_findings_count: int
    created_at: str
    updated_at: str
    version: int


class QualificationRule(TypedDict):
    id: str
    publication_id: str
    dimension: str
    allowed_values: List[str]
    points: int
    is_mandatory: bool
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    publication_id: str
    company_name: str
    contact_email: str
    job_function_code: str
    industry_code: str
    purchasing_authority_level: str
    subscription_class: str
    copies: int
    paid_amount_cents: int
    qualification_status: str
    delivery_status: str
    undeliverable_count: int
    qualification_score: int
    qualified_at: Optional[str]
    qualification_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SourceDocument(TypedDict):
    id: str
    subscriber_id: str
    doc_type: str
    captured_at: str
    storage_ref: str
    retention_expires_at: str
    purge_status: str
    purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualificationRequest(TypedDict):
    id: str
    subscriber_id: str
    source_document_id: str
    request_channel: str
    signed_at: str
    attested_job_function_code: str
    attested_industry_code: str
    attested_purchasing_authority: str
    status: str
    computed_score: int
    info_request_count: int
    reviewed_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_reason: Optional[str]
    effective_from: Optional[str]
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


# A hygiene run is an immutable execution record: it carries only `id` and
# `created_at` (PRD §2.4) — no `updated_at` and no `version`.
class HygieneRun(TypedDict):
    id: str
    publication_id: str
    run_type: str
    undeliverable_threshold: int
    executed_at: str
    posture_before: str
    posture_after: str
    undeliverable_flagged_count: int
    removed_count: int
    requalification_required_count: int
    lapsed_count: int
    statements_invalidated_count: int
    created_at: str


class CirculationStatement(TypedDict):
    id: str
    publication_id: str
    period_start: str
    period_end: str
    basis: str
    statement_type: str
    status: str
    restates_statement_id: Optional[str]
    paid_copies: int
    qualified_non_paid_copies: int
    controlled_copies_included: int
    controlled_copies_excess: int
    total_qualified_copies: int
    declared_total_copies: int
    digital_reach_verified: int
    undeliverable_pct_at_close: float
    breakdown_stale: bool
    prepared_by_user_id: str
    certified_by_user_id: Optional[str]
    filed_at: Optional[str]
    guarantees_settled_at: Optional[str]
    discrepancy_copies: Optional[int]
    discrepancy_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict):
    id: str
    statement_id: str
    auditor_org: str
    fieldwork_start: str
    fieldwork_end: str
    sample_size: int
    status: str
    sample_verified_count: int
    verified_qualified_copies: int
    open_findings_count: int
    report_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    engagement_id: str
    subscriber_id: Optional[str]
    finding_type: str
    severity: str
    affected_copies: int
    status: str
    response_count: int
    raised_by_user_id: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdvertiserContract(TypedDict):
    id: str
    publication_id: str
    advertiser_name: str
    insertion_count: int
    gross_rate_cents_per_insertion: int
    guaranteed_rate_base: int
    shortfall_tolerance_pct: float
    guarantee_status: str
    makegood_credit_pool_cents: int
    makegood_credit_committed_cents: int
    makegood_credit_waived_cents: int
    makegood_credit_available_cents: int
    created_at: str
    updated_at: str
    version: int


class MakeGoodObligation(TypedDict):
    id: str
    contract_id: str
    statement_id: str
    shortfall_copies: int
    shortfall_pct: float
    tier_factor: float
    per_insertion_credit_cents: int
    credit_cents: int
    bonus_insertions: int
    status: str
    offered_at: Optional[str]
    accepted_at: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DigitalAudienceSnapshot(TypedDict):
    id: str
    publication_id: str
    window_start: str
    window_end: str
    website_unique_visitors: int
    newsletter_sends: int
    newsletter_unique_opens: int
    overlap_pct: float
    source: str
    combined_reach_gross: int
    combined_reach_deduplicated: int
    status: str
    validated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
