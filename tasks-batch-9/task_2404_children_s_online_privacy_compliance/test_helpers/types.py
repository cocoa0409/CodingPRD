"""Domain types for the Children's Online Privacy Compliance API.

Status enumerations, the role enumeration and entity TypedDicts, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The five roles the system recognises."""

    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PRIVACY_ENGINEER = "PrivacyEngineer"
    PARENT = "Parent"
    SAFE_HARBOR_ASSESSOR = "SafeHarborAssessor"
    SAFE_HARBOR_CERTIFIER = "SafeHarborCertifier"


class DeterminationStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    GENERAL_AUDIENCE = "GENERAL_AUDIENCE"
    MIXED_AUDIENCE = "MIXED_AUDIENCE"
    CHILD_DIRECTED_PRIMARY = "CHILD_DIRECTED_PRIMARY"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class DeterminationVariant(str, Enum):
    AUDIENCE_FIRST = "AUDIENCE_FIRST"
    DESIGN_FIRST = "DESIGN_FIRST"


class SafeHarborStatus(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    CERTIFIED = "CERTIFIED"
    ASSESSMENT_DUE = "ASSESSMENT_DUE"
    LAPSED = "LAPSED"


class ServiceCategory(str, Enum):
    GAME = "GAME"
    VIDEO_PLATFORM = "VIDEO_PLATFORM"
    EDUCATION_APP = "EDUCATION_APP"
    SOCIAL_NETWORK = "SOCIAL_NETWORK"
    GENERAL_INTEREST_PORTAL = "GENERAL_INTEREST_PORTAL"


class SubjectMatterCode(str, Enum):
    CHILD_ENTERTAINMENT = "CHILD_ENTERTAINMENT"
    CHILD_EDUCATION = "CHILD_EDUCATION"
    FAMILY_MIXED = "FAMILY_MIXED"
    TEEN_LIFESTYLE = "TEEN_LIFESTYLE"
    ADULT_GENERAL = "ADULT_GENERAL"


class EvidenceKind(str, Enum):
    AUDIENCE_SAMPLE = "AUDIENCE_SAMPLE"
    DESIGN_FACTOR = "DESIGN_FACTOR"


class MeasurementMethod(str, Enum):
    PANEL = "PANEL"
    AGE_SCREEN_LOG = "AGE_SCREEN_LOG"
    SELF_REPORTED = "SELF_REPORTED"


class FactorCode(str, Enum):
    SUBJECT_MATTER = "SUBJECT_MATTER"
    VISUAL_CONTENT = "VISUAL_CONTENT"
    CHILD_CELEBRITIES = "CHILD_CELEBRITIES"
    LANGUAGE = "LANGUAGE"
    MUSIC_AUDIO = "MUSIC_AUDIO"
    ADVERTISING_PLACEMENT = "ADVERTISING_PLACEMENT"
    INTERACTIVE_DESIGN = "INTERACTIVE_DESIGN"


class FactorRating(str, Enum):
    ABSENT = "ABSENT"
    INCIDENTAL = "INCIDENTAL"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class AgeScreenMechanism(str, Enum):
    NEUTRAL_DOB_ENTRY = "NEUTRAL_DOB_ENTRY"
    AGE_RANGE_SELECT = "AGE_RANGE_SELECT"
    ACCOUNT_AGE_INHERIT = "ACCOUNT_AGE_INHERIT"


class AgeScreenStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class NeutralityViolationCode(str, Enum):
    PREFILLED_AGE = "PREFILLED_AGE"
    RETRY_ALLOWED = "RETRY_ALLOWED"
    OUTCOME_NOT_PERSISTED = "OUTCOME_NOT_PERSISTED"
    UNVERIFIED_INHERIT = "UNVERIFIED_INHERIT"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class DeliveryChannel(str, Enum):
    EMAIL = "EMAIL"
    IN_APP_MODAL = "IN_APP_MODAL"
    POSTAL = "POSTAL"
    SCHOOL_INTERMEDIARY = "SCHOOL_INTERMEDIARY"


class ContentKey(str, Enum):
    OPERATOR_IDENTITY_CONTACT = "OPERATOR_IDENTITY_CONTACT"
    ELEMENTS_COLLECTED = "ELEMENTS_COLLECTED"
    USE_PURPOSES = "USE_PURPOSES"
    THIRD_PARTY_DISCLOSURE = "THIRD_PARTY_DISCLOSURE"
    PARENTAL_RIGHTS = "PARENTAL_RIGHTS"
    NO_CONDITIONING_OF_PARTICIPATION = "NO_CONDITIONING_OF_PARTICIPATION"
    RETENTION_AND_DISPOSAL = "RETENTION_AND_DISPOSAL"


class ConsentStatus(str, Enum):
    INITIATED = "INITIATED"
    NOTICE_DELIVERED = "NOTICE_DELIVERED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class IntendedUse(str, Enum):
    PARTICIPATION_CORE = "PARTICIPATION_CORE"
    INTERNAL_OPERATIONS = "INTERNAL_OPERATIONS"
    CONTESTS_PRIZES = "CONTESTS_PRIZES"
    PERSONALIZED_ADVERTISING = "PERSONALIZED_ADVERTISING"
    THIRD_PARTY_DISCLOSURE = "THIRD_PARTY_DISCLOSURE"
    PUBLIC_POSTING = "PUBLIC_POSTING"


class ConsentMethod(str, Enum):
    EMAIL_PLUS = "EMAIL_PLUS"
    SCHOOL_AUTHORIZATION = "SCHOOL_AUTHORIZATION"
    KNOWLEDGE_BASED_AUTH = "KNOWLEDGE_BASED_AUTH"
    SIGNED_FORM_RETURN = "SIGNED_FORM_RETURN"
    PHONE_CALL_TRAINED_PERSONNEL = "PHONE_CALL_TRAINED_PERSONNEL"
    CREDIT_CARD_TRANSACTION = "CREDIT_CARD_TRANSACTION"
    GOVT_ID_MATCH = "GOVT_ID_MATCH"
    VIDEO_CONFERENCE_REVIEW = "VIDEO_CONFERENCE_REVIEW"


class RevocationReason(str, Enum):
    PARENT_REFUSAL = "PARENT_REFUSAL"
    DELETION_FULFILLED = "DELETION_FULFILLED"
    SUPERSEDED_BY_NEW_CONSENT = "SUPERSEDED_BY_NEW_CONSENT"


class DataElementCode(str, Enum):
    PERSISTENT_IDENTIFIER = "PERSISTENT_IDENTIFIER"
    GEOLOCATION_PRECISE = "GEOLOCATION_PRECISE"
    PHOTO_VIDEO_AUDIO = "PHOTO_VIDEO_AUDIO"
    VOICE_RECORDING = "VOICE_RECORDING"
    FULL_NAME = "FULL_NAME"
    EMAIL = "EMAIL"
    SCREEN_NAME = "SCREEN_NAME"
    PHONE = "PHONE"
    POSTAL_ADDRESS = "POSTAL_ADDRESS"
    SCHOOL_NAME = "SCHOOL_NAME"


class PurposeCode(str, Enum):
    PARTICIPATION_CORE = "PARTICIPATION_CORE"
    INTERNAL_OPERATIONS = "INTERNAL_OPERATIONS"
    PERSONALIZED_ADS = "PERSONALIZED_ADS"
    CONTESTS = "CONTESTS"
    SUPPORT = "SUPPORT"


class AgeScreenOutcome(str, Enum):
    UNDER_13 = "UNDER_13"
    THIRTEEN_PLUS = "THIRTEEN_PLUS"


class RecordStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SCHEDULED_FOR_DISPOSAL = "SCHEDULED_FOR_DISPOSAL"
    DISPOSED = "DISPOSED"


class RightType(str, Enum):
    REVIEW = "REVIEW"
    DELETE = "DELETE"
    REFUSE_FURTHER_COLLECTION = "REFUSE_FURTHER_COLLECTION"


class RightsRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"


class ScopeMode(str, Enum):
    PARENT_CONSENT_SCOPE = "PARENT_CONSENT_SCOPE"
    CHILD_IDENTITY_SCOPE = "CHILD_IDENTITY_SCOPE"


class IntegrationType(str, Enum):
    BEHAVIORAL_AD_NETWORK = "BEHAVIORAL_AD_NETWORK"
    CONTEXTUAL_AD_NETWORK = "CONTEXTUAL_AD_NETWORK"
    ANALYTICS = "ANALYTICS"
    SOCIAL_PLUGIN = "SOCIAL_PLUGIN"
    CDN = "CDN"


class PlacementArea(str, Enum):
    CHILD_DIRECTED_AREA = "CHILD_DIRECTED_AREA"
    GENERAL_AREA = "GENERAL_AREA"


class IntegrationStatus(str, Enum):
    DECLARED = "DECLARED"
    AUDIT_PENDING = "AUDIT_PENDING"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class DisposalMethod(str, Enum):
    CRYPTO_ERASE = "CRYPTO_ERASE"
    OVERWRITE = "OVERWRITE"
    PHYSICAL_DESTRUCTION = "PHYSICAL_DESTRUCTION"
    ANONYMIZE = "ANONYMIZE"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


# --------------------------------------------------------------------------
# Entity payload shapes.
#
# Every resource carries id + created_at. Most resources additionally carry
# updated_at and version. Determination evidence is the sole exception: it is
# append-only and carries neither updated_at nor version.
# --------------------------------------------------------------------------


class OnlineService(TypedDict):
    id: str
    name: str
    operator_organization: str
    service_category: str
    subject_matter_code: str
    determination_status: str
    compliance_posture: str
    posture_override: Optional[str]
    determination_variant_applied: Optional[str]
    design_score: float
    audience_child_share: Optional[float]
    determination_evaluated_at: Optional[str]
    safe_harbor_status: str
    safe_harbor_expires_at: Optional[str]
    active_consent_count: int
    granted_disclosure_consent_count: int
    live_child_data_element_count: int
    lifetime_collected_element_count: int
    third_party_exposure_points: int
    open_audit_count: int
    audit_decision_count: int
    evidence_sequence_counter: int
    compliance_run_sequence: int
    created_at: str
    updated_at: str
    version: int


class DeterminationEvidence(TypedDict):
    """Append-only evidence row: only id and created_at, no updated_at, no version."""

    id: str
    service_id: str
    evidence_kind: str
    measurement_method: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    total_users: Optional[int]
    users_under_13: Optional[int]
    sample_verified: Optional[bool]
    factor_code: Optional[str]
    rating: Optional[str]
    evidence_note: Optional[str]
    evidence_sequence: int
    created_at: str


class AgeScreen(TypedDict):
    id: str
    service_id: str
    mechanism: str
    default_prefilled_age: Optional[int]
    retry_allowed_on_fail: bool
    outcome_session_persisted: bool
    inherited_from_verified_account: bool
    neutrality_violation_codes: List[str]
    status: str
    revision_round: int
    activated_at: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParentalNotice(TypedDict):
    id: str
    service_id: str
    notice_label: str
    delivery_channel: str
    content_keys: List[str]
    disclosed_integration_vendors: List[str]
    missing_content_keys: List[str]
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActivityDefinition(TypedDict):
    id: str
    service_id: str
    activity_code: str
    participation_required_elements: List[str]
    created_at: str
    updated_at: str
    version: int


class ConsentRequest(TypedDict):
    id: str
    service_id: str
    notice_id: str
    parent_email: str
    child_pseudonym: str
    intended_uses: List[str]
    consent_method: str
    required_tier_at_creation: int
    method_assurance_tier: int
    status: str
    notice_delivered_at: Optional[str]
    verification_deadline_at: Optional[str]
    granted_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    verification_evidence_code: Optional[str]
    secondary_confirmation_received: bool
    created_at: str
    updated_at: str
    version: int


class ChildDataRecord(TypedDict):
    id: str
    service_id: str
    consent_request_id: str
    activity_id: str
    data_element_code: str
    purpose_code: str
    age_screen_outcome: str
    child_pseudonym: str
    status: str
    collected_at: str
    retention_days_applied: int
    disposal_method_applied: str
    disposal_due_at: str
    scheduled_run_sequence: Optional[int]
    disposed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParentalRightsRequest(TypedDict):
    id: str
    service_id: str
    consent_request_id: str
    right_type: str
    requester_email: str
    status: str
    verification_method: Optional[str]
    verification_attempt_count: int
    scope_mode: Optional[str]
    in_scope_record_count: Optional[int]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ThirdPartyIntegration(TypedDict):
    id: str
    service_id: str
    vendor_name: str
    integration_type: str
    collects_persistent_identifier: bool
    placement_area: str
    status: str
    exposure_points: int
    disclosed_in_notice: bool
    last_audit_decision_at: Optional[str]
    audit_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionSchedule(TypedDict):
    id: str
    service_id: str
    data_element_code: str
    purpose_code: str
    retention_days: int
    disposal_method: str
    effective_from: str
    effective_to: str
    defined_purpose_statement: str
    created_at: str
    updated_at: str
    version: int


class SafeHarborProgram(TypedDict):
    id: str
    program_name: str
    regulator_approved: bool
    annual_assessment_required: bool
    assessment_validity_days: int
    assessment_grace_days: int
    created_at: str
    updated_at: str
    version: int


class SafeHarborAssessment(TypedDict):
    id: str
    service_id: str
    program_id: str
    assessment_year: int
    status: str
    preparer_user_id: str
    certifier_user_id: Optional[str]
    remediation_round: int
    findings_open_count: int
    certified_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceRunSummary(TypedDict):
    """The inline summary a compliance run reports back; not a stored entity."""

    service_id: str
    run_sequence: int
    expired_consent_count: int
    scheduled_count: int
    disposed_count: int
    live_child_data_element_count_after: int
    compliance_posture_after: str
