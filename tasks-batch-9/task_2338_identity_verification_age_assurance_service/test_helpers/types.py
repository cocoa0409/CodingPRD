"""Domain types for the Identity Verification & Age Assurance API.

Entity TypedDicts, state enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_INTEGRATOR = "ClientIntegrator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REVIEW_MANAGER = "ReviewManager"
    MANUAL_REVIEWER = "ManualReviewer"
    INCLUSION_REVIEWER = "InclusionReviewer"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class IntegrationState(str, Enum):
    SANDBOX = "SANDBOX"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"


class BiometricRetentionMode(str, Enum):
    DELETE_ON_COMPLETE = "DELETE_ON_COMPLETE"
    RETAIN_90_DAYS = "RETAIN_90_DAYS"
    RETAIN_WITH_CONSENT = "RETAIN_WITH_CONSENT"


class MethodCode(str, Enum):
    DOCUMENT_SCAN = "DOCUMENT_SCAN"
    DATABASE_CHECK = "DATABASE_CHECK"
    BIOMETRIC_COMPARISON = "BIOMETRIC_COMPARISON"
    KNOWLEDGE_BASED = "KNOWLEDGE_BASED"
    VOUCHING_ATTESTATION = "VOUCHING_ATTESTATION"
    AGE_ESTIMATION = "AGE_ESTIMATION"


class BiasState(str, Enum):
    CLEARED = "CLEARED"
    MONITORED = "MONITORED"
    RESTRICTED = "RESTRICTED"


class PolicyState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class AssuranceTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class DocumentationStatus(str, Enum):
    STANDARD_DOCS = "STANDARD_DOCS"
    NO_STANDARD_DOCS = "NO_STANDARD_DOCS"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IdentityState(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AgeState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ASSURED = "ASSURED"
    FAILED = "FAILED"


class DispositionReason(str, Enum):
    SCORE_SATISFIED = "SCORE_SATISFIED"
    AGE_GATE_FAILED = "AGE_GATE_FAILED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    REVIEW_LAPSED = "REVIEW_LAPSED"
    EXPIRED_TTL = "EXPIRED_TTL"


class AgeBand(str, Enum):
    U13 = "U13"
    B13_15 = "B13_15"
    B16_17 = "B16_17"
    B18_20 = "B18_20"
    A21_PLUS = "A21_PLUS"


class AttemptState(str, Enum):
    AWAITING_EVIDENCE = "AWAITING_EVIDENCE"
    SCORED = "SCORED"
    REQUIRES_RESCORE = "REQUIRES_RESCORE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SelectionMode(str, Enum):
    CLIENT_REQUESTED = "CLIENT_REQUESTED"
    SERVER_SELECTED = "SERVER_SELECTED"
    PATHWAY_GRANTED = "PATHWAY_GRANTED"


class RejectionReason(str, Enum):
    DOCUMENT_FORGED = "DOCUMENT_FORGED"
    DOCUMENT_SUSPECT = "DOCUMENT_SUSPECT"
    LIVENESS_FAILED = "LIVENESS_FAILED"
    DATA_MISMATCH = "DATA_MISMATCH"
    KBA_FAILED = "KBA_FAILED"
    METHOD_RESTRICTED = "METHOD_RESTRICTED"
    EXPIRED_WINDOW = "EXPIRED_WINDOW"


class DocumentType(str, Enum):
    PASSPORT = "PASSPORT"
    NATIONAL_ID = "NATIONAL_ID"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    RESIDENCE_PERMIT = "RESIDENCE_PERMIT"


class DocumentAssessment(str, Enum):
    AUTHENTIC = "AUTHENTIC"
    SUSPECT = "SUSPECT"
    FORGED = "FORGED"


class CaptureModality(str, Enum):
    PASSIVE = "PASSIVE"
    ACTIVE = "ACTIVE"


class LivenessDecision(str, Enum):
    PASS = "PASS"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAIL = "FAIL"


class TemplateState(str, Enum):
    STORED = "STORED"
    PURGE_SCHEDULED = "PURGE_SCHEDULED"
    DELETED = "DELETED"


class DeletionReason(str, Enum):
    MINOR_PROTECTION = "MINOR_PROTECTION"
    POLICY_IMMEDIATE = "POLICY_IMMEDIATE"
    CONSENT_ABSENT = "CONSENT_ABSENT"
    RETENTION_EXPIRED = "RETENTION_EXPIRED"


class AgeMethod(str, Enum):
    ESTIMATION = "ESTIMATION"
    VERIFICATION = "VERIFICATION"


class AgeDecision(str, Enum):
    ASSURED = "ASSURED"
    FAILED = "FAILED"


class PathwayType(str, Enum):
    VOUCHING = "VOUCHING"
    ATTESTATION = "ATTESTATION"


class PathwayState(str, Enum):
    VOUCH_PENDING = "VOUCH_PENDING"
    ATTESTATION_PENDING = "ATTESTATION_PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class PathwayAction(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class ReviewCaseState(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    DECIDED = "DECIDED"
    WITHDRAWN = "WITHDRAWN"


class ReviewTriggerReason(str, Enum):
    FRAUD_SIGNAL = "FRAUD_SIGNAL"
    SCORE_SHORTFALL = "SCORE_SHORTFALL"
    AGE_INCONCLUSIVE = "AGE_INCONCLUSIVE"
    RESTRICTED_METHOD = "RESTRICTED_METHOD"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN_FOR_STEP_UP = "RETURN_FOR_STEP_UP"


class AuditState(str, Enum):
    COLLECTING = "COLLECTING"
    EVALUATED = "EVALUATED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    REMEDIATED = "REMEDIATED"


class CohortCode(str, Enum):
    AGE_13_17 = "AGE_13_17"
    AGE_18_24 = "AGE_18_24"
    AGE_25_44 = "AGE_25_44"
    AGE_45_64 = "AGE_45_64"
    AGE_65_PLUS = "AGE_65_PLUS"
    SKIN_TONE_I_III = "SKIN_TONE_I_III"
    SKIN_TONE_IV_VI = "SKIN_TONE_IV_VI"


class AuditEventType(str, Enum):
    SESSION_CREATED = "SESSION_CREATED"
    ATTEMPT_FINALIZED = "ATTEMPT_FINALIZED"
    STEP_UP_TRIGGERED = "STEP_UP_TRIGGERED"
    ESCALATED_TO_REVIEW = "ESCALATED_TO_REVIEW"
    REVIEW_DECIDED = "REVIEW_DECIDED"
    PATHWAY_DECIDED = "PATHWAY_DECIDED"
    METHOD_RESTRICTION_APPLIED = "METHOD_RESTRICTION_APPLIED"
    TEMPLATE_DELETED = "TEMPLATE_DELETED"
    SESSION_TERMINAL = "SESSION_TERMINAL"


# --------------------------------------------------------------------------
# Resources carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    name: str
    home_jurisdiction_code: str
    integration_state: str
    biometric_retention_mode: str
    daily_session_quota: int
    granted_review_credits: int
    reserved_review_credits: int
    available_review_credits: int
    stored_template_count: int
    pending_stepup_count: int
    consumed_review_count: int
    created_at: str
    updated_at: str
    version: int


class MethodProfile(TypedDict):
    id: str
    method_code: str
    vendor_code: str
    assurance_weight: int
    acceptance_floor_bps: int
    far_bps: int
    frr_bps: int
    strong_evidence: bool
    cost_cents: int
    estimation_mae_months: int
    band_accuracy_bps: Dict[str, int]
    bias_state: str
    restricted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationPolicy(TypedDict):
    id: str
    client_id: str
    policy_version: int
    state: str
    allowed_method_codes: List[str]
    min_assurance_score: int
    doc_authenticity_floor_bps: int
    pad_threshold_bps: int
    required_min_age_years: int
    age_buffer_multiplier_bps: int
    step_up_max_rounds: int
    alternative_pathway_enabled: bool
    published_at: Optional[str]
    retired_at: Optional[str]
    degraded_flag: bool
    created_at: str
    updated_at: str
    version: int


class VerificationSession(TypedDict):
    id: str
    client_id: str
    policy_id: str
    external_subject_ref: str
    requested_assurance_tier: str
    declared_transaction_value_cents: int
    subject_jurisdiction_code: str
    biometric_consent: bool
    documentation_status: str
    risk_score: int
    risk_level: str
    identity_state: str
    age_state: str
    assurance_score_provisional: int
    assurance_score_final: Optional[int]
    assurance_ceiling: int
    resolved_age_band: Optional[str]
    fraud_signal_count: int
    step_up_round: int
    manual_override_flag: bool
    disposition_reason: Optional[str]
    expires_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MethodAttempt(TypedDict):
    id: str
    session_id: str
    method_profile_id: str
    method_code: str
    selection_mode: str
    retry_index: int
    state: str
    evidence_quality_bps: Optional[int]
    match_score_bps: Optional[int]
    contribution_points: Optional[int]
    tamper_flag: bool
    rejection_reason: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BiometricTemplate(TypedDict):
    id: str
    session_id: str
    source_method_code: str
    state: str
    retention_expires_at: Optional[str]
    deleted_at: Optional[str]
    deletion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlternativePathway(TypedDict):
    id: str
    session_id: str
    pathway_type: str
    state: str
    voucher_reference: Optional[str]
    attestation_document_ref: Optional[str]
    reviewer_user_id: Optional[str]
    granted_points: Optional[int]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManualReviewCase(TypedDict):
    id: str
    session_id: str
    trigger_reason: str
    state: str
    assigned_by_user_id: Optional[str]
    assigned_reviewer_user_id: Optional[str]
    sla_due_at: str
    decision: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BiasAudit(TypedDict):
    id: str
    method_profile_id: str
    window_start: str
    window_end: str
    state: str
    remediation_round: int
    included_cohort_count: int
    excluded_cohort_count: int
    insufficient_sample: bool
    max_frr_bps: Optional[int]
    min_frr_bps: Optional[int]
    pooled_frr_bps: Optional[int]
    disparity_ratio_max_to_min_bps: Optional[int]
    disparity_ratio_max_to_pooled_bps: Optional[int]
    worst_cohort_code: Optional[str]
    evaluated_by_user_id: Optional[str]
    remediated_by_user_id: Optional[str]
    remediated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Write-once observations: id + created_at only, never updated_at / version
# --------------------------------------------------------------------------
class DocumentCapture(TypedDict):
    id: str
    attempt_id: str
    document_type: str
    required_feature_count: int
    passed_feature_count: int
    tamper_signal_count: int
    mrz_checksum_valid: bool
    base_score_bps: int
    tamper_tier_multiplier_bps: int
    tamper_penalty_bps: int
    authenticity_score_bps: int
    assessment: str
    created_at: str


class LivenessCheck(TypedDict):
    id: str
    attempt_id: str
    capture_modality: str
    pad_score_bps: int
    retry_index: int
    effective_threshold_bps: int
    decision: str
    created_at: str


class AgeAssuranceResult(TypedDict):
    id: str
    session_id: str
    method: str
    estimated_age_months: Optional[int]
    date_of_birth: Optional[str]
    source_vendor_code: Optional[str]
    mae_months_snapshot: Optional[int]
    buffer_months: int
    effective_age_months: int
    resolved_band: str
    documented_accuracy_bps: Optional[int]
    decision: str
    created_at: str


class CohortMetric(TypedDict):
    id: str
    bias_audit_id: str
    cohort_code: str
    attempt_count: int
    false_reject_count: int
    false_accept_count: int
    frr_bps: int
    far_bps: int
    included_in_ratio: bool
    created_at: str


class AuditEvent(TypedDict):
    id: str
    session_id: str
    event_type: str
    actor_role: str
    actor_user_id: Optional[str]
    payload_summary: Any
    occurred_at: str
    created_at: str
