"""Domain types for the Likeness Rights Clearance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Three record types are immutable once written and carry
neither ``updated_at`` nor ``version``; their TypedDicts omit both fields.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    RIGHTS_ADMINISTRATOR = "RightsAdministrator"
    TALENT_REPRESENTATIVE = "TalentRepresentative"
    ESTATE_REPRESENTATIVE = "EstateRepresentative"
    LICENSEE_PRODUCER = "LicenseeProducer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

class UnionCode(str, Enum):
    NONE = "NONE"
    SAG_AFTRA = "SAG_AFTRA"
    AFM = "AFM"


class LifeStatus(str, Enum):
    LIVING = "LIVING"
    DECEASED = "DECEASED"


class RightsPosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MediaType(str, Enum):
    ADVERTISING = "ADVERTISING"
    FEATURE_FILM = "FEATURE_FILM"
    EPISODIC = "EPISODIC"
    VIDEO_GAME = "VIDEO_GAME"
    SOCIAL = "SOCIAL"


class Channel(str, Enum):
    ADVERTISING = "ADVERTISING"
    ENTERTAINMENT = "ENTERTAINMENT"


class DisclosurePlacement(str, Enum):
    METADATA_ONLY = "METADATA_ONLY"
    END_CARD = "END_CARD"
    PRE_ROLL = "PRE_ROLL"
    PERSISTENT_BUG = "PERSISTENT_BUG"


class EstateAuthorityStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class GrantorKind(str, Enum):
    TALENT = "TALENT"
    ESTATE = "ESTATE"


class Exclusivity(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class ConsentGrantStatus(str, Enum):
    PENDING_COUNTERSIGN = "PENDING_COUNTERSIGN"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SuspensionReason(str, Enum):
    DEATH_PENDING_ESTATE = "DEATH_PENDING_ESTATE"
    COMPLIANCE_HOLD = "COMPLIANCE_HOLD"


class AssetKind(str, Enum):
    FACE_SCAN = "FACE_SCAN"
    VOICE_SAMPLE = "VOICE_SAMPLE"
    MOTION_CAPTURE = "MOTION_CAPTURE"


class StorageClass(str, Enum):
    ENCRYPTED_VAULT = "ENCRYPTED_VAULT"
    COLD_ARCHIVE = "COLD_ARCHIVE"


class BiometricAssetStatus(str, Enum):
    STORED = "STORED"
    PURGE_SCHEDULED = "PURGE_SCHEDULED"
    LEGAL_HOLD = "LEGAL_HOLD"
    PURGED = "PURGED"


class ReplicaKind(str, Enum):
    FACE = "FACE"
    VOICE = "VOICE"
    FULL_PERFORMANCE = "FULL_PERFORMANCE"


class DigitalReplicaStatus(str, Enum):
    BUILT = "BUILT"
    APPROVED_FOR_USE = "APPROVED_FOR_USE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class QuarantineReason(str, Enum):
    CONSENT_REVOKED = "CONSENT_REVOKED"
    SOURCE_LEGAL_HOLD = "SOURCE_LEGAL_HOLD"
    ESTATE_PENDING = "ESTATE_PENDING"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RejectionReason(str, Enum):
    OFF_BRAND = "OFF_BRAND"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    QUALITY = "QUALITY"
    REVIEW_WINDOW_LAPSED = "REVIEW_WINDOW_LAPSED"
    REVISION_LIMIT_REACHED = "REVISION_LIMIT_REACHED"


class DistributionStatus(str, Enum):
    ISSUED = "ISSUED"
    LIVE = "LIVE"
    REMOVAL_PENDING = "REMOVAL_PENDING"
    REMOVAL_CONFIRMED = "REMOVAL_CONFIRMED"


class ComplianceStatus(str, Enum):
    PENDING_LABEL = "PENDING_LABEL"
    LABELED = "LABELED"
    VERIFIED = "VERIFIED"
    NON_COMPLIANT = "NON_COMPLIANT"


class RemovalReason(str, Enum):
    TERM_EXPIRED = "TERM_EXPIRED"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    REPLICA_QUARANTINED = "REPLICA_QUARANTINED"
    PERFORMANCE_WITHDRAWN = "PERFORMANCE_WITHDRAWN"


class EntryType(str, Enum):
    INITIAL_CREATION = "INITIAL_CREATION"
    UNION_TOPUP = "UNION_TOPUP"
    PER_USE_PROVISIONAL = "PER_USE_PROVISIONAL"
    PER_USE_FINAL = "PER_USE_FINAL"
    REVERSAL = "REVERSAL"


class DetectionSource(str, Enum):
    MONITORING_FEED = "MONITORING_FEED"
    SWEEP = "SWEEP"
    MANUAL_REPORT = "MANUAL_REPORT"


class InfringementCaseStatus(str, Enum):
    DETECTED = "DETECTED"
    DISMISSED_LICENSED = "DISMISSED_LICENSED"
    DISMISSED_NO_ACTION = "DISMISSED_NO_ACTION"
    TAKEDOWN_ISSUED = "TAKEDOWN_ISSUED"
    RESOLVED_REMOVED = "RESOLVED_REMOVED"
    LEGAL_ESCALATED = "LEGAL_ESCALATED"
    CLOSED_SETTLED = "CLOSED_SETTLED"
    CLOSED_LITIGATED = "CLOSED_LITIGATED"


class ClosureOutcome(str, Enum):
    LICENSED_USE_CONFIRMED = "LICENSED_USE_CONFIRMED"
    BELOW_ENFORCEMENT_THRESHOLD = "BELOW_ENFORCEMENT_THRESHOLD"
    VOLUNTARY_REMOVAL = "VOLUNTARY_REMOVAL"
    SETTLED = "SETTLED"
    LITIGATED = "LITIGATED"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------

class Talent(TypedDict):
    id: str
    legal_name: str
    domicile_state_code: str
    union_code: str
    life_status: str
    date_of_death: Optional[str]
    postmortem_rights_until: Optional[str]
    postmortem_registration_number: Optional[str]
    rights_posture: str
    open_removal_obligation_count: int
    legal_hold_asset_count: int
    lifetime_compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class EstateAuthority(TypedDict):
    id: str
    talent_id: str
    executor_name: str
    court_document_ref: str
    registration_number: Optional[str]
    status: str
    submitted_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentGrant(TypedDict):
    id: str
    talent_id: str
    estate_authority_id: Optional[str]
    grantor_kind: str
    permitted_media_types: List[str]
    permitted_use_notes: str
    territory_codes: List[str]
    exclusivity: str
    effective_from: str
    effective_until: str
    effective_end_actual: Optional[str]
    initial_creation_fee_cents: int
    per_use_base_fee_cents: int
    talent_share_pct: float
    agency_share_pct: float
    administrator_share_pct: float
    approval_required: bool
    revocable: bool
    union_code_snapshot: Optional[str]
    status: str
    suspension_reason: Optional[str]
    drafted_by_user_id: str
    countersigned_at: Optional[str]
    initial_compensation_cents: int
    union_topup_cents: int
    total_compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class BiometricAsset(TypedDict):
    id: str
    talent_id: str
    consent_grant_id: str
    asset_kind: str
    capture_ref: str
    storage_class: str
    payload_digest: Optional[str]
    status: str
    retention_until: str
    purge_due_at: Optional[str]
    purged_at: Optional[str]
    held_from_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DigitalReplica(TypedDict):
    id: str
    talent_id: str
    consent_grant_id: str
    replica_kind: str
    source_asset_ids: List[str]
    build_ref: str
    status: str
    approved_at: Optional[str]
    approved_by_user_id: Optional[str]
    quarantine_reason: Optional[str]
    held_from_status: Optional[str]
    open_license_count: int
    created_at: str
    updated_at: str
    version: int


class GeneratedPerformance(TypedDict):
    id: str
    digital_replica_id: str
    licensee_user_id: str
    licensee_name: str
    media_type: str
    territory_codes: List[str]
    intended_use_description: str
    projected_impressions: int
    scheduled_first_use_at: str
    review_status: str
    revision_round: int
    review_deadline: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    review_note: Optional[str]
    provisional_compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class UsageLicense(TypedDict):
    id: str
    generated_performance_id: str
    licensee_user_id: str
    channel: str
    territory_codes: List[str]
    distribution_start: str
    distribution_end: str
    actual_impressions: int
    distribution_reference: Optional[str]
    distribution_status: str
    compliance_status: str
    disclosure_required: bool
    disclosure_placement: Optional[str]
    disclosure_label_text: Optional[str]
    disclosure_verified_by_user_id: Optional[str]
    per_use_final_cents: int
    compliance_surcharge_cents: int
    license_total_cents: int
    removal_deadline: Optional[str]
    removal_reason: Optional[str]
    removal_confirmed_at: Optional[str]
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class InfringementCase(TypedDict):
    id: str
    talent_id: str
    matched_usage_license_id: Optional[str]
    detection_source: str
    suspect_url: str
    detected_channel: str
    detected_state_code: str
    detected_view_count: int
    match_confidence: float
    severity_score: float
    use_state_rights_until: Optional[str]
    enforceable_under_use_state: bool
    status: str
    triaged_by_user_id: Optional[str]
    escalated_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    takedown_issued_at: Optional[str]
    legal_hold_applied_count: int
    closure_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Immutable records — id + created_at only, no updated_at and no version
# --------------------------------------------------------------------------

class StateLawProfile(TypedDict):
    id: str
    state_code: str
    postmortem_rights_years: int
    postmortem_requires_registration: bool
    biometric_retention_max_days: int
    deletion_grace_days: int
    removal_window_days: int
    disclosure_required_advertising: bool
    disclosure_required_entertainment: bool
    min_disclosure_rank_advertising: int
    min_disclosure_rank_entertainment: int
    created_at: str


class UnionMinimumSchedule(TypedDict):
    id: str
    union_code: str
    media_type: str
    effective_from: str
    minimum_initial_cents: int
    minimum_per_use_cents: int
    created_at: str


class CompensationEntry(TypedDict):
    id: str
    talent_id: str
    consent_grant_id: str
    generated_performance_id: Optional[str]
    usage_license_id: Optional[str]
    reverses_entry_id: Optional[str]
    entry_type: str
    amount_cents: int
    talent_share_cents: int
    agency_share_cents: int
    administrator_share_cents: int
    memo: str
    posted_at: str
    created_at: str
