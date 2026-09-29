"""Domain types for the Food Manager Certification API.

Entity TypedDicts, status enums and the role enum, named exactly as the PRD
names them. Every persisted resource carries id, created_at, updated_at and
version (PRD 2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROVIDER_ADMIN = "ProviderAdmin"
    PROCTOR = "Proctor"
    CANDIDATE = "Candidate"
    HEALTH_OFFICER = "HealthOfficer"


class AccreditationBody(str, Enum):
    ANAB_CFP = "ANAB_CFP"
    ANSI_LEGACY = "ANSI_LEGACY"
    STATE_ONLY = "STATE_ONLY"


class Language(str, Enum):
    EN = "EN"
    ES = "ES"
    ZH = "ZH"
    VI = "VI"


class ExamFormStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ComplianceStatus(str, Enum):
    NOT_CERTIFIED = "NOT_CERTIFIED"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"
    NON_COMPLIANT = "NON_COMPLIANT"


class ProctorRegistrationStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class SuspendedReason(str, Enum):
    AUDIT_FAILURE = "AUDIT_FAILURE"
    RISK_THRESHOLD_BREACH = "RISK_THRESHOLD_BREACH"


class RiskVariant(str, Enum):
    ROLLING_WINDOW = "ROLLING_WINDOW"
    LIFETIME_CUMULATIVE = "LIFETIME_CUMULATIVE"


class BatchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class AccessCodeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class BundleType(str, Enum):
    EXAM_ONLY = "EXAM_ONLY"
    COURSE_PLUS_EXAM = "COURSE_PLUS_EXAM"


class AccommodationType(str, Enum):
    EXTRA_TIME = "EXTRA_TIME"
    READER_ASSIST = "READER_ASSIST"
    SEPARATE_ROOM = "SEPARATE_ROOM"
    TRANSLATED_FORM = "TRANSLATED_FORM"


class AccommodationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    REMOTE = "REMOTE"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    INVALIDATED = "INVALIDATED"


class ProctoringStatus(str, Enum):
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    ASSIGNED = "ASSIGNED"
    PENDING_REPROCTOR = "PENDING_REPROCTOR"
    ATTESTED = "ATTESTED"
    INCIDENT_UNDER_REVIEW = "INCIDENT_UNDER_REVIEW"
    CLEARED = "CLEARED"
    COMPROMISED = "COMPROMISED"


class IdDocumentType(str, Enum):
    GOVT_PHOTO_ID = "GOVT_PHOTO_ID"
    PASSPORT = "PASSPORT"
    MILITARY_ID = "MILITARY_ID"


class ScoreReportStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOIDED = "VOIDED"


class IncidentCategory(str, Enum):
    IMPERSONATION = "IMPERSONATION"
    PROHIBITED_MATERIAL = "PROHIBITED_MATERIAL"
    ROOM_SCAN_REFUSAL = "ROOM_SCAN_REFUSAL"
    CONTENT_DISCLOSURE = "CONTENT_DISCLOSURE"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class RevocationReason(str, Enum):
    SCORE_VOIDED = "SCORE_VOIDED"
    JURISDICTION_WITHDRAWAL = "JURISDICTION_WITHDRAWAL"


class ReminderTier(str, Enum):
    T_180 = "T_180"
    T_90 = "T_90"
    T_30 = "T_30"
    T_LAPSED = "T_LAPSED"


class LocalRegistrationStatus(str, Enum):
    FILED = "FILED"
    POSTED = "POSTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    DELINQUENT = "DELINQUENT"
    WITHDRAWN = "WITHDRAWN"


# --- Entity TypedDicts ---------------------------------------------------
# Every persisted entity type carries all four common properties.


class Jurisdiction(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    accepted_accreditation_bodies: List[str]
    accepted_languages: List[str]
    accepts_remote_proctoring: bool
    min_passing_score_override: Optional[int]
    requires_local_registration: bool
    posting_deadline_days: int
    recert_cycle_months: int
    exam_fee_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class TrainingProvider(TypedDict):
    id: str
    legal_name: str
    jurisdiction_id: str
    contact_email: str
    lifetime_credited_cents: int
    lifetime_charged_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ExamForm(TypedDict):
    id: str
    form_code: str
    version_label: str
    language: str
    accreditation_body: str
    scored_item_count: int
    pretest_item_count: int
    national_cut_score: int
    base_minutes: int
    translated_extra_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestingSite(TypedDict):
    id: str
    name: str
    jurisdiction_id: str
    seat_count: int
    address_line: str
    languages_supported: List[str]
    reserved_seat_minutes: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    full_name: str
    email: str
    preferred_language: str
    training_provider_id: str
    jurisdiction_id: str
    security_hold: bool
    substantiated_incident_count: int
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class Proctor(TypedDict):
    id: str
    full_name: str
    email: str
    training_provider_id: str
    roles_held: List[str]
    languages_certified: List[str]
    remote_certified: bool
    registration_status: str
    proctored_session_count: int
    substantiated_incident_weight_total: int
    risk_score: float
    risk_variant_applied: str
    reserved_minutes: int
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessCodeBatch(TypedDict):
    id: str
    training_provider_id: str
    exam_form_id: str
    line_items: List[dict]
    quantity_purchased: int
    total_price_cents: int
    available_count: int
    assigned_count: int
    consumed_count: int
    voided_count: int
    expires_at: str
    status: str
    void_gross_credit_cents: Optional[int]
    void_restock_fee_cents: Optional[int]
    void_net_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AccessCode(TypedDict):
    id: str
    batch_id: str
    candidate_id: Optional[str]
    code: str
    bundle_type: str
    status: str
    assigned_at: Optional[str]
    consumed_at: Optional[str]
    course_completed_at: Optional[str]
    course_instructor_proctor_id: Optional[str]
    assignment_release_count: int
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict):
    id: str
    candidate_id: str
    accommodation_type: str
    requested_multiplier: float
    documentation_ref: str
    requested_language: Optional[str]
    status: str
    approved_multiplier: Optional[float]
    decision_reason: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamSession(TypedDict):
    id: str
    candidate_id: str
    exam_form_id: str
    access_code_id: str
    testing_site_id: Optional[str]
    proctor_id: Optional[str]
    accommodation_request_id: Optional[str]
    delivery_mode: str
    scheduled_start_at: str
    allowed_minutes: int
    scheduled_end_at: str
    session_status: str
    proctoring_status: str
    id_document_type: Optional[str]
    id_document_expires_on: Optional[str]
    biometric_match_score: Optional[int]
    proctor_attestation: bool
    identity_verified_at: Optional[str]
    checked_in_at: Optional[str]
    started_at: Optional[str]
    submitted_at: Optional[str]
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class ScoreReport(TypedDict):
    id: str
    exam_session_id: str
    exam_form_id: str
    raw_correct_count: int
    pretest_correct_count: int
    voided_item_count: int
    voided_correct_count: int
    provisional_scaled_score: int
    final_scaled_score: Optional[int]
    effective_cut_score: int
    pass_flag: Optional[bool]
    status: str
    finalized_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityIncident(TypedDict):
    id: str
    exam_session_id: str
    reported_by_proctor_id: str
    category: str
    severity: str
    narrative: str
    severity_weight: int
    status: str
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    candidate_id: str
    score_report_id: str
    jurisdiction_id: str
    superseded_by_certificate_id: Optional[str]
    certificate_number: str
    issued_at: str
    expires_at: str
    recert_window_opens_at: str
    status: str
    issuance_fee_cents: int
    reminder_tiers_sent: List[str]
    recert_authorized_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LocalRegistration(TypedDict):
    id: str
    certificate_id: str
    jurisdiction_id: str
    establishment_name: str
    establishment_address: str
    posting_location: Optional[str]
    filed_at: str
    posting_deadline_at: str
    posted_at: Optional[str]
    status: str
    rejection_reason: Optional[str]
    verified_by_user_id: Optional[str]
    refile_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceSummary(TypedDict):
    candidate_id: str
    compliance_status: str
    active_certificate_id: Optional[str]
    certificate_expires_at: Optional[str]
    recert_window_opens_at: Optional[str]
    local_registration_status: Optional[str]
    reminder_tiers_sent: List[str]
    open_incident_count: int


class ComplianceRunSummary(TypedDict):
    run_epoch: str
    certificates_expired_count: int
    registrations_delinquent_count: int
    batches_expired_count: int
    reminder_notices_sent_count: int
    notified_certificate_ids: List[str]
