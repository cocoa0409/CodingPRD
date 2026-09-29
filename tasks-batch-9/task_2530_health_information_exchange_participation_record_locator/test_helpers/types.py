"""Domain types for the Health Information Exchange Record Locator API.

Status enums, role enum and entity TypedDicts. Field names are exactly the
names the PRD uses; nothing here is abbreviated or renamed.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    HIE_ADMIN = "HieAdmin"
    PARTICIPANT_ADMIN = "ParticipantAdmin"
    CLINICIAN = "Clinician"
    PRIVACY_OFFICER = "PrivacyOfficer"
    PUBLIC_HEALTH_OFFICER = "PublicHealthOfficer"


# ── Status enums ─────────────────────────────────────────────────────────

class OnboardingStatus(str, Enum):
    APPLIED = "APPLIED"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    AGREEMENT_EXECUTED = "AGREEMENT_EXECUTED"
    CONFORMANCE_TESTING = "CONFORMANCE_TESTING"
    REMEDIATION = "REMEDIATION"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED = "TERMINATED"


class OrgType(str, Enum):
    HOSPITAL = "HOSPITAL"
    CLINIC = "CLINIC"
    LAB = "LAB"
    HEALTH_PLAN = "HEALTH_PLAN"
    PUBLIC_HEALTH = "PUBLIC_HEALTH"


class FeeTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNGRADED = "UNGRADED"


class ConformanceProfile(str, Enum):
    QUERY_RESPONDER = "QUERY_RESPONDER"
    ADT_PUBLISHER = "ADT_PUBLISHER"
    DOCUMENT_SOURCE = "DOCUMENT_SOURCE"
    ADT_SUBSCRIBER = "ADT_SUBSCRIBER"
    PUBLIC_HEALTH_CONDUIT = "PUBLIC_HEALTH_CONDUIT"


class ConformanceTestStatus(str, Enum):
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class FailureCategory(str, Enum):
    SECURITY = "SECURITY"
    PATIENT_ID_INTEGRITY = "PATIENT_ID_INTEGRITY"
    VOCABULARY = "VOCABULARY"
    TRANSPORT = "TRANSPORT"
    PAYLOAD_STRUCTURE = "PAYLOAD_STRUCTURE"


class ConsentModel(str, Enum):
    OPT_IN = "OPT_IN"
    OPT_OUT = "OPT_OUT"


class SensitiveCategory(str, Enum):
    BEHAVIORAL_HEALTH = "BEHAVIORAL_HEALTH"
    SUD = "SUD"
    HIV = "HIV"
    REPRODUCTIVE = "REPRODUCTIVE"
    GENETIC = "GENETIC"


class ConsentPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ScoreVariantMode(str, Enum):
    DETERMINISTIC_FIRST = "DETERMINISTIC_FIRST"
    PROBABILISTIC_ONLY = "PROBABILISTIC_ONLY"


class ThresholdConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Sex(str, Enum):
    M = "M"
    F = "F"
    O = "O"
    U = "U"


class MatchState(str, Enum):
    CLUSTERED = "CLUSTERED"
    QUARANTINED = "QUARANTINED"
    WITHDRAWN_FROM_INDEX = "WITHDRAWN_FROM_INDEX"


class ClusterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MERGED_AWAY = "MERGED_AWAY"


class ScoreVariant(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    PROBABILISTIC = "PROBABILISTIC"


class MatchLinkStatus(str, Enum):
    PROPOSED = "PROPOSED"
    AUTO_LINKED = "AUTO_LINKED"
    PENDING_REVIEW = "PENDING_REVIEW"
    LINKED = "LINKED"
    REJECTED = "REJECTED"
    UNLINKED = "UNLINKED"


class DirectiveType(str, Enum):
    OPT_IN = "OPT_IN"
    OPT_OUT = "OPT_OUT"
    SENSITIVE_CATEGORY_RESTRICTION = "SENSITIVE_CATEGORY_RESTRICTION"


class DirectiveScope(str, Enum):
    ALL_PARTICIPANTS = "ALL_PARTICIPANTS"
    SINGLE_PARTICIPANT = "SINGLE_PARTICIPANT"


class DirectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class PurposeOfUse(str, Enum):
    TREATMENT = "TREATMENT"
    PAYMENT = "PAYMENT"
    OPERATIONS = "OPERATIONS"
    PUBLIC_HEALTH = "PUBLIC_HEALTH"
    EMERGENCY = "EMERGENCY"


class ConsentDecision(str, Enum):
    PERMITTED = "PERMITTED"
    PARTIAL_SEGMENTED = "PARTIAL_SEGMENTED"
    DENIED_OPT_OUT = "DENIED_OPT_OUT"
    DENIED_SEGMENTED = "DENIED_SEGMENTED"
    PERMITTED_EMERGENCY = "PERMITTED_EMERGENCY"
    PERMITTED_PUBLIC_HEALTH = "PERMITTED_PUBLIC_HEALTH"
    NO_MATCH = "NO_MATCH"


class AuditAction(str, Enum):
    DISCLOSED = "DISCLOSED"
    WITHHELD = "WITHHELD"
    BREAK_GLASS_DISCLOSED = "BREAK_GLASS_DISCLOSED"


class SuppressionReason(str, Enum):
    OPT_OUT = "OPT_OUT"
    SENSITIVE_CATEGORY = "SENSITIVE_CATEGORY"
    PURPOSE_RESTRICTED = "PURPOSE_RESTRICTED"
    CONTRIBUTOR_NOT_PARTICIPATING = "CONTRIBUTOR_NOT_PARTICIPATING"


class EmergencyCategory(str, Enum):
    LIFE_THREATENING = "LIFE_THREATENING"
    UNCONSCIOUS_PATIENT = "UNCONSCIOUS_PATIENT"
    DISASTER = "DISASTER"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    JUSTIFIED = "JUSTIFIED"
    UNJUSTIFIED = "UNJUSTIFIED"


class SubscriptionScope(str, Enum):
    PATIENT_PANEL = "PATIENT_PANEL"
    CLUSTER = "CLUSTER"
    PUBLIC_HEALTH_CONDUIT = "PUBLIC_HEALTH_CONDUIT"


class EventType(str, Enum):
    ADMISSION = "ADMISSION"
    DISCHARGE = "DISCHARGE"
    TRANSFER = "TRANSFER"


class SubscriptionStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FeedType(str, Enum):
    ADT = "ADT"
    CCDA = "CCDA"
    LAB_RESULT = "LAB_RESULT"


class DataFeedStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    MONITORED = "MONITORED"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class BasisVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RECONCILED = "RECONCILED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOID = "VOID"


# ── Entity TypedDicts ────────────────────────────────────────────────────
# Participant, ConformanceTest, ConsentPolicy, MatchThresholdConfig,
# PatientRecord, IdentityCluster, MatchLink, ConsentDirective,
# BreakGlassAccess, NotificationSubscription, DataFeed and
# ParticipationInvoice carry id + created_at + updated_at + version.
# RecordLocatorQuery, AccessAuditEntry and FeedQualitySample are immutable
# once written and carry ONLY id + created_at.


class Participant(TypedDict):
    id: str
    legal_name: str
    org_type: str
    declared_annual_patient_volume: int
    primary_contact_email: str
    onboarding_status: str
    agreement_version: Optional[str]
    agreement_signed_at: Optional[str]
    agreement_executed_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    suspension_reason: Optional[str]
    conformance_attempt_count: int
    consecutive_failed_attempts: int
    remediation_count: int
    passed_profiles: List[str]
    fee_tier: str
    provisional_monthly_fee_cents: int
    quality_score: Optional[float]
    quality_grade: str
    sanction_points_active: int
    outstanding_balance_cents: int
    active_subscription_count: int
    created_at: str
    updated_at: str
    version: int


class ConformanceTest(TypedDict):
    id: str
    participant_id: str
    profile: str
    attempt_number: int
    scheduled_start: str
    scheduled_end: str
    status: str
    assertions_total: Optional[int]
    assertions_passed: Optional[int]
    pass_rate: Optional[float]
    failure_categories: List[str]
    critical_failure: bool
    waiver_reason: Optional[str]
    executed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentPolicy(TypedDict):
    id: str
    policy_version: str
    model: str
    sensitive_categories_segmented: List[str]
    default_share_for_treatment: bool
    effective_from: str
    effective_until: Optional[str]
    status: str
    activated_by_user_id: Optional[str]
    directive_count: int
    created_at: str
    updated_at: str
    version: int


class MatchThresholdConfig(TypedDict):
    id: str
    config_label: str
    auto_link_threshold: float
    review_lower_bound: float
    score_variant_mode: str
    weight_family_name: float
    weight_given_name: float
    weight_birth_date: float
    weight_ssn_last4: float
    weight_postal_code: float
    weight_phone_digits: float
    partial_credit_factor: float
    status: str
    tuned_by_user_id: Optional[str]
    activated_by_user_id: Optional[str]
    scored_link_count: int
    created_at: str
    updated_at: str
    version: int


class PatientRecord(TypedDict):
    id: str
    participant_id: str
    source_mrn: str
    given_name: str
    family_name: str
    birth_date: str
    sex: str
    ssn_last4: Optional[str]
    postal_code: Optional[str]
    phone_digits: Optional[str]
    sensitive_categories: List[str]
    cluster_id: Optional[str]
    prior_cluster_id: Optional[str]
    match_state: str
    completeness_score: int
    created_at: str
    updated_at: str
    version: int


class IdentityCluster(TypedDict):
    id: str
    primary_record_id: Optional[str]
    member_record_count: int
    participant_count: int
    pending_review_link_count: int
    status: str
    merged_into_cluster_id: Optional[str]
    active_directive_count: int
    created_at: str
    updated_at: str
    version: int


class MatchLink(TypedDict):
    id: str
    left_record_id: str
    right_record_id: str
    threshold_config_id: str
    cluster_id: Optional[str]
    merged_away_cluster_id: Optional[str]
    match_score: float
    score_variant: str
    field_agreement_map: Dict[str, Any]
    status: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    unlink_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentDirective(TypedDict):
    id: str
    cluster_id: str
    policy_id: Optional[str]
    directive_type: str
    scope: str
    scoped_participant_id: Optional[str]
    restricted_categories: List[str]
    effective_from: str
    status: str
    supersedes_directive_id: Optional[str]
    recorded_by_user_id: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecordLocatorQuery(TypedDict):
    """Immutable: carries only id and created_at besides its own fields."""
    id: str
    querying_participant_id: str
    clinician_user_id: str
    purpose_of_use: str
    family_name: str
    given_name: str
    birth_date: str
    sex: Optional[str]
    ssn_last4: Optional[str]
    postal_code: Optional[str]
    phone_digits: Optional[str]
    break_glass_id: Optional[str]
    cluster_id: Optional[str]
    top_candidate_score: Optional[float]
    governing_policy_id: Optional[str]
    governing_directive_id: Optional[str]
    consent_decision: str
    disclosed_record_count: int
    withheld_record_count: int
    withheld_categories: List[str]
    created_at: str


class AccessAuditEntry(TypedDict):
    """Immutable: carries only id and created_at besides its own fields."""
    id: str
    query_id: str
    record_id: str
    disclosing_participant_id: str
    action: str
    suppression_reason: Optional[str]
    sensitive_category_hit: List[str]
    reviewed: bool
    created_at: str


class BreakGlassAccess(TypedDict):
    id: str
    cluster_id: str
    invoking_participant_id: str
    invoking_clinician_user_id: str
    emergency_category: str
    justification_text: str
    opened_at: str
    expires_at: str
    session_status: str
    review_status: str
    review_claimed_by_user_id: Optional[str]
    reviewer_user_id: Optional[str]
    review_note: Optional[str]
    decided_at: Optional[str]
    disclosed_record_count: int
    disclosed_sensitive_count: int
    sanction_points_awarded: int
    created_at: str
    updated_at: str
    version: int


class NotificationSubscription(TypedDict):
    id: str
    subscriber_participant_id: str
    subscription_scope: str
    cluster_id: Optional[str]
    event_types: List[str]
    delivery_endpoint_url: str
    activating_conformance_test_id: Optional[str]
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataFeed(TypedDict):
    id: str
    participant_id: str
    feed_type: str
    generation: int
    status: str
    latest_reject_rate: Optional[float]
    sample_count: int
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedQualitySample(TypedDict):
    """Immutable: carries only id and created_at besides its own fields."""
    id: str
    data_feed_id: str
    period_start: str
    period_end: str
    messages_received: int
    messages_rejected: int
    required_fields_missing_count: int
    duplicate_count: int
    timeliness_p95_seconds: int
    reject_rate: float
    created_at: str


class ParticipationInvoice(TypedDict):
    id: str
    participant_id: str
    billing_period_start: str
    billing_period_end: str
    basis_variant: str
    due_date: str
    billable_volume_units: int
    tier_charge_breakdown: Dict[str, int]
    volume_fee_cents: int
    base_platform_fee_cents: int
    quality_grade_snapshot: Optional[str]
    quality_multiplier: float
    total_cents: int
    amount_paid_cents: int
    status: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
