"""Domain types: entity TypedDicts, status enums, role enum.

Every one of the fifteen resource types carries the same four server-managed
properties: id, created_at, updated_at and version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PUBLISHER_ADMIN = "PublisherAdmin"
    RELEASE_MANAGER = "ReleaseManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_REVIEWER = "PlatformReviewer"
    PLATFORM_APPEAL_BOARD = "PlatformAppealBoard"
    PLATFORM_POLICY_ADMIN = "PlatformPolicyAdmin"
    AUDITOR = "Auditor"


PUBLISHER_SIDE_ROLES = [
    UserRole.PUBLISHER_ADMIN.value,
    UserRole.RELEASE_MANAGER.value,
    UserRole.COMPLIANCE_OFFICER.value,
]
PLATFORM_SIDE_ROLES = [
    UserRole.PLATFORM_REVIEWER.value,
    UserRole.PLATFORM_APPEAL_BOARD.value,
    UserRole.PLATFORM_POLICY_ADMIN.value,
    UserRole.AUDITOR.value,
]
ALL_ROLES = PUBLISHER_SIDE_ROLES + PLATFORM_SIDE_ROLES


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CommerceProgramTier(str, Enum):
    SMALL_BUSINESS = "SMALL_BUSINESS"
    STANDARD = "STANDARD"


class CredentialStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    COMPROMISED = "COMPROMISED"


class CredentialType(str, Enum):
    DISTRIBUTION_CERT = "DISTRIBUTION_CERT"
    PROVISIONING_PROFILE = "PROVISIONING_PROFILE"


class KeyCustody(str, Enum):
    HSM = "HSM"
    CLOUD_MANAGED = "CLOUD_MANAGED"
    LOCAL_KEYCHAIN = "LOCAL_KEYCHAIN"


class RevocationReason(str, Enum):
    SUPERSEDED = "SUPERSEDED"
    MANUAL = "MANUAL"
    COMPROMISE_CASCADE = "COMPROMISE_CASCADE"


class Platform(str, Enum):
    IOS = "IOS"
    ANDROID = "ANDROID"


class Entitlement(str, Enum):
    IN_APP_PURCHASE = "IN_APP_PURCHASE"
    EXTERNAL_PAYMENT_LINK = "EXTERNAL_PAYMENT_LINK"
    PUSH_NOTIFICATIONS = "PUSH_NOTIFICATIONS"
    BACKGROUND_LOCATION = "BACKGROUND_LOCATION"


class ListingState(str, Enum):
    DRAFT = "DRAFT"
    METADATA_COMPLETE = "METADATA_COMPLETE"
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class DistributionState(str, Enum):
    NOT_DISTRIBUTED = "NOT_DISTRIBUTED"
    PHASED_ROLLOUT = "PHASED_ROLLOUT"
    FULLY_RELEASED = "FULLY_RELEASED"
    PAUSED = "PAUSED"
    ROLLED_BACK = "ROLLED_BACK"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PostureReasonCode(str, Enum):
    ACCOUNT_NOT_IN_GOOD_STANDING = "ACCOUNT_NOT_IN_GOOD_STANDING"
    IMPACT_OVERDUE = "IMPACT_OVERDUE"
    CRITICAL_FINDING_OPEN = "CRITICAL_FINDING_OPEN"
    MEMBERSHIP_EXPIRED = "MEMBERSHIP_EXPIRED"
    NO_ACTIVE_DISTRIBUTION_CERT = "NO_ACTIVE_DISTRIBUTION_CERT"
    COMPLIANCE_INDEX_BELOW_FLOOR = "COMPLIANCE_INDEX_BELOW_FLOOR"
    OPEN_IMPACT_ASSESSMENT = "OPEN_IMPACT_ASSESSMENT"


class PrimaryCategory(str, Enum):
    GAMES = "GAMES"
    FINANCE = "FINANCE"
    HEALTH = "HEALTH"
    SOCIAL = "SOCIAL"
    PRODUCTIVITY = "PRODUCTIVITY"
    KIDS = "KIDS"


class ListingAction(str, Enum):
    COMPLETE_METADATA = "COMPLETE_METADATA"
    LIST = "LIST"
    DELIST = "DELIST"
    RETURN_TO_DRAFT = "RETURN_TO_DRAFT"


class GuidelineCategory(str, Enum):
    SAFETY = "SAFETY"
    PRIVACY = "PRIVACY"
    COMMERCE = "COMMERCE"
    LEGAL = "LEGAL"
    DESIGN = "DESIGN"


class GuidelineStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class SelfReviewStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    STALE = "STALE"
    WAIVED_BY_PLATFORM = "WAIVED_BY_PLATFORM"


class SelfReviewOutcome(str, Enum):
    START = "START"
    PASS = "PASS"
    FAIL = "FAIL"


class SubmissionState(str, Enum):
    DRAFT = "DRAFT"
    PRE_REVIEW_PASSED = "PRE_REVIEW_PASSED"
    WAITING_FOR_REVIEW = "WAITING_FOR_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    METADATA_REJECTED = "METADATA_REJECTED"
    APPEAL_PENDING = "APPEAL_PENDING"
    REJECTED_FINAL = "REJECTED_FINAL"
    BLOCKED_INVALID_SIGNING = "BLOCKED_INVALID_SIGNING"
    DEVELOPER_WITHDRAWN = "DEVELOPER_WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ReleaseMode(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    PHASED = "PHASED"
    MANUAL = "MANUAL"


class SubmissionChannel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class PriorityBand(str, Enum):
    EXPEDITED = "EXPEDITED"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class PreReviewBlockingReason(str, Enum):
    METADATA_INCOMPLETE = "METADATA_INCOMPLETE"
    SCREENSHOT_SET_EMPTY = "SCREENSHOT_SET_EMPTY"
    AGE_RATING_UNDERSTATED = "AGE_RATING_UNDERSTATED"
    TRACKING_CONSENT_PROMPT_MISSING = "TRACKING_CONSENT_PROMPT_MISSING"
    PRIVACY_DISCLOSURE_INACCURATE = "PRIVACY_DISCLOSURE_INACCURATE"
    CRITICAL_FINDING_UNRESOLVED = "CRITICAL_FINDING_UNRESOLVED"
    GUIDELINE_MAPPING_INCOMPLETE = "GUIDELINE_MAPPING_INCOMPLETE"
    SIGNING_CREDENTIAL_INVALID = "SIGNING_CREDENTIAL_INVALID"


PRE_REVIEW_REASON_TIE_ORDER = [
    "METADATA_INCOMPLETE",
    "SCREENSHOT_SET_EMPTY",
    "AGE_RATING_UNDERSTATED",
    "TRACKING_CONSENT_PROMPT_MISSING",
    "PRIVACY_DISCLOSURE_INACCURATE",
    "CRITICAL_FINDING_UNRESOLVED",
    "GUIDELINE_MAPPING_INCOMPLETE",
    "SIGNING_CREDENTIAL_INVALID",
]


class DeviceClass(str, Enum):
    PHONE_65 = "PHONE_65"
    TABLET_129 = "TABLET_129"


class DataType(str, Enum):
    PRECISE_LOCATION = "PRECISE_LOCATION"
    CONTACTS = "CONTACTS"
    DEVICE_ID = "DEVICE_ID"
    EMAIL = "EMAIL"
    PURCHASE_HISTORY = "PURCHASE_HISTORY"
    HEALTH = "HEALTH"
    USAGE_DATA = "USAGE_DATA"


class ObservedPurpose(str, Enum):
    ANALYTICS = "ANALYTICS"
    ADVERTISING = "ADVERTISING"
    APP_FUNCTIONALITY = "APP_FUNCTIONALITY"
    PERSONALIZATION = "PERSONALIZATION"
    THIRD_PARTY_SHARING = "THIRD_PARTY_SHARING"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"
    DISMISSED = "DISMISSED"


class TriageAction(str, Enum):
    DISPUTE = "DISPUTE"
    RECONCILE = "RECONCILE"
    DISMISS = "DISMISS"


class Disposition(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CONTESTED = "CONTESTED"


class AppealDisposition(str, Enum):
    PENDING = "PENDING"
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"


class AppealState(str, Enum):
    SUBMITTED = "SUBMITTED"
    BOARD_REVIEW = "BOARD_REVIEW"
    OVERTURNED = "OVERTURNED"
    PARTIALLY_OVERTURNED = "PARTIALLY_OVERTURNED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"


class AppealType(str, Enum):
    GUIDELINE_INTERPRETATION = "GUIDELINE_INTERPRETATION"
    FACTUAL_ERROR = "FACTUAL_ERROR"


class ExpediteState(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    CONSUMED = "CONSUMED"
    REFUNDED = "REFUNDED"


class JustificationCategory(str, Enum):
    CRITICAL_BUG = "CRITICAL_BUG"
    SECURITY_FIX = "SECURITY_FIX"
    TIME_SENSITIVE_EVENT = "TIME_SENSITIVE_EVENT"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RolloutState(str, Enum):
    SCHEDULED = "SCHEDULED"
    PHASE_ACTIVE = "PHASE_ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


class RolloutMode(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    PHASED = "PHASED"


class ItemType(str, Enum):
    CONSUMABLE = "CONSUMABLE"
    NON_CONSUMABLE = "NON_CONSUMABLE"
    SUBSCRIPTION = "SUBSCRIPTION"
    EXTERNAL_PAYMENT_LINK = "EXTERNAL_PAYMENT_LINK"


class EntitlementClass(str, Enum):
    DIGITAL_CONTENT = "DIGITAL_CONTENT"
    PHYSICAL_GOOD = "PHYSICAL_GOOD"
    SERVICE = "SERVICE"


class CommerceItemStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REMOVED = "REMOVED"


class ImpactStatus(str, Enum):
    OPEN = "OPEN"
    IN_ASSESSMENT = "IN_ASSESSMENT"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    OVERDUE = "OVERDUE"
    REMEDIATED = "REMEDIATED"
    ACCEPTED_NO_CHANGE = "ACCEPTED_NO_CHANGE"


class ImpactAction(str, Enum):
    START = "START"
    REQUIRE_REMEDIATION = "REQUIRE_REMEDIATION"
    ACCEPT_NO_CHANGE = "ACCEPT_NO_CHANGE"
    MARK_REMEDIATED = "MARK_REMEDIATED"


class AgeRatingDimension(str, Enum):
    VIOLENCE = "VIOLENCE"
    SEXUAL_CONTENT = "SEXUAL_CONTENT"
    DRUGS_ALCOHOL = "DRUGS_ALCOHOL"
    GAMBLING_SIMULATED = "GAMBLING_SIMULATED"
    HORROR = "HORROR"
    PROFANITY = "PROFANITY"
    FLOOR_RULE = "FLOOR_RULE"


class PublisherAccount(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    program_status: str
    commerce_program_tier: str
    membership_paid_through_at: str
    enforcement_reason_code: Optional[str]
    standing_score_rolling_365: float
    standing_score_lifetime: float
    expedite_credits_remaining: int
    rejection_strike_count: int
    settlement_finalized_periods: List[str]
    created_at: str
    updated_at: str
    version: int


class SigningCredential(TypedDict):
    id: str
    publisher_account_id: str
    credential_type: str
    linked_cert_id: Optional[str]
    platform: str
    key_custody: str
    entitlements: List[str]
    not_before: str
    not_after: str
    status: str
    revocation_reason: Optional[str]
    compromised_at: Optional[str]
    blocked_submission_count: int
    created_at: str
    updated_at: str
    version: int


class AppRecord(TypedDict):
    id: str
    publisher_account_id: str
    bundle_id: str
    platform: str
    display_name: str
    primary_category: str
    listing_state: str
    distribution_state: str
    compliance_posture: str
    posture_reason_codes: List[str]
    feature_compliance_index: float
    live_submission_id: Optional[str]
    released_share_pct: float
    held_back_share_pct: float
    rollback_count: int
    created_at: str
    updated_at: str
    version: int


class GuidelineRule(TypedDict):
    id: str
    rule_code: str
    title: str
    category: str
    severity_weight: int
    remediation_grace_days: int
    version_label: str
    effective_from: str
    status: str
    supersedes_rule_id: Optional[str]
    requires_feature_mapping: bool
    published_at: Optional[str]
    impacted_app_count: int
    created_at: str
    updated_at: str
    version: int


class FeatureMapping(TypedDict):
    id: str
    app_record_id: str
    guideline_rule_id: str
    feature_code: str
    self_review_status: str
    risk_weight: float
    evidence_ref: Optional[str]
    attested_by_user_id: Optional[str]
    attested_at: Optional[str]
    staled_by_rule_id: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    app_record_id: str
    signing_credential_id: str
    review_window_id: Optional[str]
    build_number: int
    version_string: str
    release_mode: str
    submission_channel: str
    state: str
    age_rating_answers: Optional[Dict[str, Any]]
    attested_age_rating: Optional[int]
    derived_age_rating: Optional[int]
    age_rating_driving_dimension: Optional[str]
    declared_privacy_items: List[Dict[str, Any]]
    tracking_consent_prompt_present: bool
    disclosure_accuracy_score_provisional: Optional[float]
    disclosure_accuracy_score_final: Optional[float]
    pre_review_passed: bool
    pre_review_blocking_reasons: List[str]
    pre_review_checked_at: Optional[str]
    attested_by_user_id: Optional[str]
    queued_at: Optional[str]
    provisional_deadline_at: Optional[str]
    priority_score: Optional[float]
    priority_band: Optional[str]
    effective_review_deadline_at: Optional[str]
    reviewed_by_user_id: Optional[str]
    decided_at: Optional[str]
    rejected_at: Optional[str]
    resubmission_count: int
    metadata_locale_count: int
    created_at: str
    updated_at: str
    version: int


class MetadataLocale(TypedDict):
    id: str
    submission_id: str
    locale: str
    is_primary: bool
    title: str
    subtitle: Optional[str]
    keywords: Optional[str]
    promotional_text: Optional[str]
    screenshot_counts: Dict[str, int]
    required_device_classes: List[str]
    is_complete: bool
    created_at: str
    updated_at: str
    version: int


class BehaviorFinding(TypedDict):
    id: str
    submission_id: str
    data_type: str
    observed_purpose: str
    observed_linked_to_user: bool
    observed_tracking: bool
    endpoint_domain: str
    severity: str
    scanner_confidence: float
    detected_at: str
    status: str
    triaged_by_user_id: Optional[str]
    triage_justification: Optional[str]
    triaged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RejectionReason(TypedDict):
    id: str
    submission_id: str
    guideline_rule_id: str
    reason_code: str
    severity: str
    detail: str
    recorded_at: str
    recorded_by_user_id: str
    developer_response: Optional[str]
    disposition: str
    appeal_disposition: str
    created_at: str
    updated_at: str
    version: int


class AppealRequest(TypedDict):
    id: str
    submission_id: str
    appeal_type: str
    argument: str
    cited_rejection_reason_ids: List[str]
    state: str
    filed_at: str
    filed_by_user_id: str
    board_started_at: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    rationale: Optional[str]
    overturned_rejection_reason_ids: List[str]
    overturn_ratio: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ExpediteRequest(TypedDict):
    id: str
    submission_id: str
    publisher_account_id: str
    justification_category: str
    justification: str
    state: str
    requested_at: str
    granted_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision_rationale: Optional[str]
    consumed_at: Optional[str]
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewCapacityWindow(TypedDict):
    id: str
    platform: str
    reviewer_pool_code: str
    starts_at: str
    ends_at: str
    capacity_slots: int
    status: str
    slots_reserved: int
    slots_consumed: int
    slots_available: int
    created_at: str
    updated_at: str
    version: int


class RolloutPlan(TypedDict):
    id: str
    app_record_id: str
    submission_id: str
    mode: str
    scheduled_start_at: str
    projected_end_at: str
    state: str
    phase_index: int
    released_share_pct: float
    held_back_share_pct: float
    phase_entered_at: Optional[str]
    pause_reason_code: Optional[str]
    rollback_reason_code: Optional[str]
    halt_distribution: bool
    completed_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommerceItem(TypedDict):
    id: str
    app_record_id: str
    item_type: str
    reference_name: str
    price_tier_cents: int
    entitlement_class: str
    external_link_url: Optional[str]
    subscriber_retention_months: int
    status: str
    rejection_note: Optional[str]
    reported_gross_cents: int
    reported_period_label: Optional[str]
    commission_rate_applied: Optional[float]
    commission_cents: int
    created_at: str
    updated_at: str
    version: int


class ImpactAssessment(TypedDict):
    id: str
    app_record_id: str
    guideline_rule_id: str
    status: str
    affected_feature_codes: List[str]
    exposure_factor: float
    impact_severity: float
    remediation_deadline_at: str
    opened_at: str
    assessed_by_user_id: Optional[str]
    assessed_at: Optional[str]
    note: Optional[str]
    remediated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
