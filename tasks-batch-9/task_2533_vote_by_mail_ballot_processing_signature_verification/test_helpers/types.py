"""Domain types: status enums, role enum, entity TypedDicts."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ELECTIONS_ADMIN = "ElectionsAdmin"
    ELECTIONS_CLERK = "ElectionsClerk"
    SIGNATURE_REVIEWER = "SignatureReviewer"
    CANVASS_SUPERVISOR = "CanvassSupervisor"
    OBSERVER = "Observer"


class ElectionPosture(str, Enum):
    PRE_MAIL = "PRE_MAIL"
    MAILING = "MAILING"
    RECEIVING = "RECEIVING"
    CANVASS_LOCKED = "CANVASS_LOCKED"
    CERTIFIED = "CERTIFIED"


class ReconciliationStatus(str, Enum):
    IN_BALANCE = "IN_BALANCE"
    OUT_OF_BALANCE = "OUT_OF_BALANCE"


class PartyAffiliation(str, Enum):
    DEM = "DEM"
    REP = "REP"
    NPP = "NPP"
    OTHER = "OTHER"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    CANCELLED = "CANCELLED"


class UocavaStatus(str, Enum):
    NONE = "NONE"
    MILITARY = "MILITARY"
    OVERSEAS = "OVERSEAS"


class TrainingStatus(str, Enum):
    UNTRAINED = "UNTRAINED"
    TRAINED = "TRAINED"
    CERTIFIED_LEAD = "CERTIFIED_LEAD"


class BallotRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ADDRESS_HOLD = "ADDRESS_HOLD"
    ADDRESS_CLEARED = "ADDRESS_CLEARED"
    APPROVED = "APPROVED"
    MAILED = "MAILED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RequestChannel(str, Enum):
    ONLINE = "ONLINE"
    PAPER = "PAPER"
    PHONE = "PHONE"


class DeliveryMethod(str, Enum):
    MAIL = "MAIL"
    EMAIL_UOCAVA = "EMAIL_UOCAVA"


class ForwardingClass(str, Enum):
    UNKNOWN = "UNKNOWN"
    SAME_ADDRESS = "SAME_ADDRESS"
    FORWARDABLE = "FORWARDABLE"
    NON_FORWARDABLE = "NON_FORWARDABLE"


class AddressVerificationStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class NcoaResult(str, Enum):
    MATCH_SAME = "MATCH_SAME"
    MATCH_FORWARDABLE = "MATCH_FORWARDABLE"
    MATCH_NON_FORWARDABLE = "MATCH_NON_FORWARDABLE"
    NO_MATCH = "NO_MATCH"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class MailingBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class BatchType(str, Enum):
    UOCAVA = "UOCAVA"
    DOMESTIC_INITIAL = "DOMESTIC_INITIAL"
    SUPPLEMENTAL = "SUPPLEMENTAL"


class BallotPacketStatus(str, Enum):
    QUEUED = "QUEUED"
    MAILED = "MAILED"
    RETURNED = "RETURNED"
    UNDELIVERABLE = "UNDELIVERABLE"
    SPOILED = "SPOILED"


class IntakeChannel(str, Enum):
    USPS = "USPS"
    DROPBOX = "DROPBOX"
    IN_PERSON = "IN_PERSON"


class Timeliness(str, Enum):
    TIMELY = "TIMELY"
    TIMELY_BY_POSTMARK = "TIMELY_BY_POSTMARK"
    PROVISIONAL_TIMELY_POSTMARK = "PROVISIONAL_TIMELY_POSTMARK"
    UNTIMELY = "UNTIMELY"


class SignatureStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    ESCALATED = "ESCALATED"
    CURE_REQUIRED = "CURE_REQUIRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CustodyStatus(str, Enum):
    SEALED = "SEALED"
    SEPARATED = "SEPARATED"
    COUNTED = "COUNTED"
    SEQUESTERED = "SEQUESTERED"
    SUPERSEDED_BY_REMAKE = "SUPERSEDED_BY_REMAKE"


class ChallengeStatus(str, Enum):
    NONE = "NONE"
    CHALLENGED = "CHALLENGED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"


class SignatureReviewStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    MISSING_SIGNATURE = "MISSING_SIGNATURE"
    ABSTAIN = "ABSTAIN"


class ChallengeOutcome(str, Enum):
    SUSTAIN = "SUSTAIN"
    OVERRULE = "OVERRULE"


class CureOutcome(str, Enum):
    CURE = "CURE"
    DEFICIENT = "DEFICIENT"


class CureNoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    UNDER_EVIDENCE_REVIEW = "UNDER_EVIDENCE_REVIEW"
    CURED = "CURED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class RemakeRecordStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ObserverSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"


class StationArea(str, Enum):
    INTAKE = "INTAKE"
    SIGNATURE_REVIEW = "SIGNATURE_REVIEW"
    SEPARATION = "SEPARATION"
    REMAKE = "REMAKE"


class CureReasonCode(str, Enum):
    MISSING_SIGNATURE = "MISSING_SIGNATURE"
    SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"


class EvidenceType(str, Enum):
    SIGNED_AFFIDAVIT = "SIGNED_AFFIDAVIT"
    ID_COPY = "ID_COPY"
    WITNESS_ATTESTATION = "WITNESS_ATTESTATION"


class SubmissionChannel(str, Enum):
    MAIL = "MAIL"
    EMAIL = "EMAIL"
    IN_PERSON = "IN_PERSON"
    PORTAL = "PORTAL"


class DeficiencyReasonCode(str, Enum):
    AFFIRMATION_UNSIGNED = "AFFIRMATION_UNSIGNED"
    WRONG_EVIDENCE_TYPE = "WRONG_EVIDENCE_TYPE"
    ILLEGIBLE = "ILLEGIBLE"


class RemakeReasonCode(str, Enum):
    DAMAGED = "DAMAGED"
    UNREADABLE_MARKS = "UNREADABLE_MARKS"
    DUPLICATE_BALLOT = "DUPLICATE_BALLOT"
    TORN_ENVELOPE = "TORN_ENVELOPE"


class ChallengeReasonCode(str, Enum):
    SIGNATURE_DISPUTE = "SIGNATURE_DISPUTE"
    IDENTITY_DISPUTE = "IDENTITY_DISPUTE"
    DUPLICATE_VOTE = "DUPLICATE_VOTE"
    ENVELOPE_TAMPERING = "ENVELOPE_TAMPERING"


class UndeliverableReasonCode(str, Enum):
    NO_SUCH_ADDRESS = "NO_SUCH_ADDRESS"
    MOVED_NO_FORWARD = "MOVED_NO_FORWARD"
    REFUSED = "REFUSED"
    VACANT = "VACANT"


class SuspensionReasonCode(str, Enum):
    ADDRESS_NON_FORWARDABLE = "ADDRESS_NON_FORWARDABLE"
    PACKET_UNDELIVERABLE = "PACKET_UNDELIVERABLE"


class ConfirmationEvidenceType(str, Enum):
    SIGNED_CONFIRMATION_CARD = "SIGNED_CONFIRMATION_CARD"
    IN_PERSON_UPDATE = "IN_PERSON_UPDATE"
    ONLINE_PORTAL_UPDATE = "ONLINE_PORTAL_UPDATE"


class TransparencyEventType(str, Enum):
    REQUEST_LOGGED = "REQUEST_LOGGED"
    ENVELOPE_INTAKE = "ENVELOPE_INTAKE"
    SIGNATURE_DECISION = "SIGNATURE_DECISION"
    SIGNATURE_ESCALATION = "SIGNATURE_ESCALATION"
    CURE_ISSUED = "CURE_ISSUED"
    CURE_ADJUDICATED = "CURE_ADJUDICATED"
    CURE_EXPIRED = "CURE_EXPIRED"
    SEPARATION_RUN = "SEPARATION_RUN"
    REMAKE_COMPLETED = "REMAKE_COMPLETED"
    REMAKE_VOIDED = "REMAKE_VOIDED"
    CHALLENGE_FILED = "CHALLENGE_FILED"
    CHALLENGE_ADJUDICATED = "CHALLENGE_ADJUDICATED"
    OBSERVER_SESSION_OPENED = "OBSERVER_SESSION_OPENED"
    OBSERVER_SESSION_REVOKED = "OBSERVER_SESSION_REVOKED"
    POSTURE_CHANGED = "POSTURE_CHANGED"
    BATCH_DISPATCHED = "BATCH_DISPATCHED"
    BATCH_CANCELLED = "BATCH_CANCELLED"
    PACKET_UNDELIVERABLE = "PACKET_UNDELIVERABLE"
    ENROLLMENT_SUSPENDED = "ENROLLMENT_SUSPENDED"
    ENROLLMENT_REINSTATED = "ENROLLMENT_REINSTATED"
    PROVISIONAL_REFERRAL = "PROVISIONAL_REFERRAL"


# --- Entity shapes -------------------------------------------------------------
# Entities that carry the common lifecycle fields expose id, created_at,
# updated_at and version. The two immutable audit artifacts (cure evidence and
# transparency log entries) expose only id and created_at.


class Election(TypedDict):
    id: str
    name: str
    election_date: str
    uocava_send_deadline_date: str
    domestic_send_deadline_date: str
    return_deadline_at: str
    postmark_grace_days: int
    cure_window_days: int
    postage_budget_cents: int
    posture: str
    packets_mailed_count: int
    envelopes_received_count: int
    outstanding_packet_count: int
    undeliverable_packet_count: int
    countable_envelope_count: int
    attributable_ballot_count: int
    rejected_envelope_count: int
    provisional_referral_count: int
    open_cure_count: int
    canvass_days: int
    canvass_lock_at: str
    postage_committed_cents: int
    postage_actual_cents: int
    reconciliation_status: str
    separation_run_sequence: int
    canvass_sweep_index: int
    created_at: str
    updated_at: str
    version: int


class Voter(TypedDict):
    id: str
    full_name: str
    party_affiliation: str
    registration_status: str
    residence_address: str
    mailing_address: Optional[str]
    uocava_status: str
    signature_on_file_count: int
    last_signature_update_at: str
    permanent_absentee_active: bool
    provisional_ballot_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict):
    id: str
    full_name: str
    party_affiliation: str
    training_status: str
    training_completed_at: Optional[str]
    training_expires_at: Optional[str]
    curriculum_version: Optional[str]
    active_review_count: int
    completed_review_count: int
    created_at: str
    updated_at: str
    version: int


class BallotRequest(TypedDict):
    id: str
    voter_id: str
    election_id: str
    request_channel: str
    delivery_method: str
    permanent_flag: bool
    status: str
    mailing_address_snapshot: str
    forwarding_class: str
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddressVerification(TypedDict):
    id: str
    ballot_request_id: str
    status: str
    ncoa_result: Optional[str]
    verified_mailing_address: Optional[str]
    forwardable: Optional[bool]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermanentAbsenteeEnrollment(TypedDict):
    id: str
    voter_id: str
    status: str
    consecutive_undeliverable_count: int
    last_confirmation_at: Optional[str]
    suspension_reason_code: Optional[str]
    reinstated_count: int
    created_at: str
    updated_at: str
    version: int


class MailingBatch(TypedDict):
    id: str
    election_id: str
    batch_type: str
    scheduled_send_date: str
    status: str
    required_send_by_date: str
    packet_count: int
    estimated_postage_cents: int
    actual_postage_cents: Optional[int]
    sealed_at: Optional[str]
    dispatched_at: Optional[str]
    cancellation_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BallotPacket(TypedDict):
    id: str
    mailing_batch_id: str
    ballot_request_id: str
    packet_weight_grams: int
    packet_postage_cents: int
    packet_serial: str
    batch_sequence: int
    status: str
    mailed_at: Optional[str]
    undeliverable_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnEnvelope(TypedDict):
    id: str
    ballot_packet_id: str
    remade_from_envelope_id: Optional[str]
    intake_channel: str
    postmark_date: Optional[str]
    postmark_legible: bool
    received_at: str
    preliminary_timeliness: str
    final_timeliness: Optional[str]
    signature_status: str
    custody_status: str
    challenge_status: str
    review_round_count: int
    resolved_signature_confidence: Optional[float]
    separation_run_sequence: Optional[int]
    challenge_reason_code: Optional[str]
    challenge_findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SignatureReview(TypedDict):
    id: str
    return_envelope_id: str
    reviewer_id: str
    review_round: int
    status: str
    decision: Optional[str]
    similarity_score: Optional[int]
    confidence_score: Optional[float]
    notes: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CureNotice(TypedDict):
    id: str
    return_envelope_id: str
    reason_code: str
    status: str
    issued_at: str
    cure_deadline_at: str
    open_cure_count_at_issue: int
    canvass_days_at_issue: int
    evidence_submission_count: int
    deficiency_count: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CureEvidence(TypedDict):
    id: str
    cure_notice_id: str
    evidence_type: str
    submission_channel: str
    affirmation_signed: bool
    received_at: str
    accepted: Optional[bool]
    deficiency_reason_code: Optional[str]
    created_at: str


class RemakeRecord(TypedDict):
    id: str
    original_envelope_id: str
    team_member_a_reviewer_id: str
    team_member_b_reviewer_id: str
    reason_code: str
    session_start_at: str
    session_end_at: str
    status: str
    remade_serial: Optional[str]
    remade_envelope_id: Optional[str]
    completed_at: Optional[str]
    voided_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObserverAccessSession(TypedDict):
    id: str
    election_id: str
    observer_user_id: str
    observer_name: str
    organization: str
    party_affiliation: str
    station_area: str
    window_start_at: str
    window_end_at: str
    status: str
    revocation_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransparencyLogEntry(TypedDict):
    id: str
    election_id: str
    sequence: int
    event_type: str
    actor_role: Optional[str]
    actor_user_id: Optional[str]
    subject_entity: str
    subject_id: str
    ballot_content_disclosed: bool
    summary: str
    recorded_at: str
    created_at: str
