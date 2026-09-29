"""Domain types for the Archival Clearance API: status enums, value enums, entity TypedDicts.

Every enum value and field name below is taken verbatim from PRD.md.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PRODUCTION_ADMIN = "ProductionAdmin"
    ARCHIVE_RESEARCHER = "ArchiveResearcher"
    CLEARANCE_SUPERVISOR = "ClearanceSupervisor"
    RIGHTS_HOLDER_REP = "RightsHolderRep"
    LEGAL_COUNSEL = "LegalCounsel"


ALL_ROLES = [r.value for r in UserRole]


# ─── Production (PRD §3.1) ───────────────────────────────────────────────────

class ProductionStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    CLEARANCE = "CLEARANCE"
    LOCKED = "LOCKED"
    DELIVERED = "DELIVERED"
    ABANDONED = "ABANDONED"


class ProductionPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


# ─── Archive and rate card (PRD §3.2) ────────────────────────────────────────

class ArchiveHolderType(str, Enum):
    FILM_ARCHIVE = "FILM_ARCHIVE"
    NEWS_ARCHIVE = "NEWS_ARCHIVE"
    STUDIO = "STUDIO"
    RECORD_LABEL = "RECORD_LABEL"
    MUSIC_PUBLISHER = "MUSIC_PUBLISHER"
    INDIVIDUAL = "INDIVIDUAL"


class ArchiveMfnPolicy(str, Enum):
    NONE = "NONE"
    RATE_MFN = "RATE_MFN"


class ArchiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RateCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# ─── Asset (PRD §3.1) ────────────────────────────────────────────────────────

class AssetType(str, Enum):
    ARCHIVAL_FOOTAGE = "ARCHIVAL_FOOTAGE"
    MUSIC = "MUSIC"


class AssetUsagePurpose(str, Enum):
    CRITICAL_COMMENTARY = "CRITICAL_COMMENTARY"
    ILLUSTRATIVE_BACKGROUND = "ILLUSTRATIVE_BACKGROUND"


class AssetRightsBasis(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    LICENSED = "LICENSED"
    FAIR_USE = "FAIR_USE"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"


class AssetLicensingStatus(str, Enum):
    UNCLEARED = "UNCLEARED"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    PARTIALLY_CLEARED = "PARTIALLY_CLEARED"
    CLEARED = "CLEARED"
    LAPSED = "LAPSED"


class AssetDepictionStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    OBTAINED = "OBTAINED"
    BLOCKED = "BLOCKED"


# The four "open" licensing statuses of PRD §2.8.
OPEN_LICENSING_STATUSES = [
    AssetLicensingStatus.UNCLEARED.value,
    AssetLicensingStatus.IN_NEGOTIATION.value,
    AssetLicensingStatus.PARTIALLY_CLEARED.value,
    AssetLicensingStatus.LAPSED.value,
]


# ─── Source candidate (PRD §3.2) ─────────────────────────────────────────────

class SourceCandidateAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    ELEMENT_MISSING = "ELEMENT_MISSING"
    RIGHTS_UNCLEAR = "RIGHTS_UNCLEAR"
    WITHDRAWN = "WITHDRAWN"


class SourceCandidateSelectionStatus(str, Enum):
    NOT_SELECTED = "NOT_SELECTED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


# ─── Licence (PRD §3.3, §3.4) ────────────────────────────────────────────────

class LicenseRightsLeg(str, Enum):
    FOOTAGE = "FOOTAGE"
    MASTER = "MASTER"
    PUBLISHING = "PUBLISHING"


class LicenseMedia(str, Enum):
    THEATRICAL = "THEATRICAL"
    BROADCAST = "BROADCAST"
    STREAMING = "STREAMING"
    ALL_MEDIA = "ALL_MEDIA"


class LicenseTerritory(str, Enum):
    WORLD = "WORLD"
    DOMESTIC = "DOMESTIC"


class LicenseWindowClass(str, Enum):
    FESTIVAL_ONLY = "FESTIVAL_ONLY"
    ALL_MEDIA_WINDOW = "ALL_MEDIA_WINDOW"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    LAPSED = "LAPSED"


# The summed set of the licence money ledger (PRD §2.9).
LIVE_LICENSE_STATUSES = [
    LicenseStatus.EXECUTED.value,
    LicenseStatus.ACTIVE.value,
    LicenseStatus.EXPIRING.value,
]


class NegotiationParty(str, Enum):
    LICENSOR = "LICENSOR"
    PRODUCER = "PRODUCER"


# ─── Fair use and opinion letters (PRD §3.5) ─────────────────────────────────

class FairUseWeightingVariant(str, Enum):
    TRANSFORMATIVE_WEIGHTED = "TRANSFORMATIVE_WEIGHTED"
    MARKET_HARM_WEIGHTED = "MARKET_HARM_WEIGHTED"


class FairUseAnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class OpinionLetterRiskRating(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class OpinionLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    WITHDRAWN = "WITHDRAWN"


# ─── Subject releases (PRD §3.6) ─────────────────────────────────────────────

class SubjectReleaseType(str, Enum):
    SUBJECT_RELEASE = "SUBJECT_RELEASE"
    LIFE_RIGHTS = "LIFE_RIGHTS"
    DEPICTION_AGREEMENT = "DEPICTION_AGREEMENT"


class SubjectReleaseApprovalRights(str, Enum):
    NONE = "NONE"
    ROUGH_CUT_APPROVAL = "ROUGH_CUT_APPROVAL"
    FINAL_APPROVAL = "FINAL_APPROVAL"


class SubjectReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SIGNED = "SIGNED"
    REFUSED = "REFUSED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_WITHHELD = "APPROVAL_WITHHELD"


# The live blocker set of the depiction-window rule (PRD §3.6).
LIVE_RELEASE_STATUSES = [
    SubjectReleaseStatus.SENT.value,
    SubjectReleaseStatus.REVISION_REQUESTED.value,
    SubjectReleaseStatus.SIGNED.value,
    SubjectReleaseStatus.APPROVAL_GRANTED.value,
]


# ─── Clearance chart, E&O, delivery (PRD §3.7, §3.8) ─────────────────────────

class ClearanceChartStatus(str, Enum):
    PINNED = "PINNED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class EOApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CLEARED_TO_BIND = "CLEARED_TO_BIND"
    BOUND = "BOUND"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    DECLINED = "DECLINED"


class EOReviewType(str, Enum):
    LEGAL = "LEGAL"
    UNDERWRITING = "UNDERWRITING"


class EOReviewOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EOReviewStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DeliveryPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    DELIVERED = "DELIVERED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


# ─── Entity shapes ───────────────────────────────────────────────────────────
# Resources carrying id + created_at + updated_at + version (PRD §2.4).

class Production(TypedDict):
    id: str
    title: str
    delivery_deadline_date: str
    festival_premiere_date: Optional[str]
    eo_carrier_name: Optional[str]
    status: str
    posture: str
    asset_count: int
    cleared_asset_count: int
    open_asset_count: int
    committed_fee_cents: int
    sweep_epoch: int
    created_at: str
    updated_at: str
    version: int


class Archive(TypedDict):
    id: str
    name: str
    holder_type: str
    mfn_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    archive_id: str
    base_rate_per_30s_cents: int
    minimum_fee_cents: int
    festival_minimum_fee_cents: int
    tier1_max_seconds: int
    tier2_max_seconds: int
    tier2_rate_multiplier: float
    tier3_rate_multiplier: float
    media_multiplier_theatrical: float
    media_multiplier_broadcast: float
    media_multiplier_streaming: float
    media_multiplier_all_media: float
    territory_multiplier_world: float
    territory_multiplier_domestic: float
    term_multiplier_per_year: float
    festival_window_multiplier: float
    all_media_window_multiplier: float
    effective_from_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    production_id: str
    asset_type: str
    title: str
    timecode_in_seconds: int
    timecode_out_seconds: int
    duration_seconds: int
    usage_purpose: str
    depiction_subject_key: Optional[str]
    pd_attestation_reference: Optional[str]
    selected_source_candidate_id: Optional[str]
    rights_basis: str
    licensing_status: str
    depiction_status: str
    lapse_count: int
    created_at: str
    updated_at: str
    version: int


class SourceCandidate(TypedDict):
    id: str
    asset_id: str
    archive_id: str
    availability_status: str
    quoted_rate_per_30s_cents: Optional[int]
    provenance_confidence: Optional[int]
    selection_status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    production_id: str
    asset_id: str
    archive_id: str
    rate_card_id: str
    rights_leg: str
    media: str
    territory: str
    window_class: str
    term_months: int
    term_start_date: str
    term_end_date: str
    billable_units: int
    rate_card_fee_cents: int
    current_proposed_fee_cents: int
    mfn_requested: bool
    mfn_benchmark_fee_cents: int
    mfn_topup_cents: int
    executed_fee_cents: Optional[int]
    round_count: int
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: a negotiation round is append-only and carries only id and
# created_at — it has no updated_at field and no version field.
class NegotiationRound(TypedDict):
    id: str
    license_id: str
    round_number: int
    party: str
    proposed_fee_cents: int
    note: Optional[str]
    license_status_after: str
    license_version_after: int
    created_at: str


class FairUseAnalysis(TypedDict):
    id: str
    asset_id: str
    transformative_score: int
    nature_score: int
    amount_used_score: int
    market_harm_score: int
    weighting_variant: str
    strength_score: float
    status: str
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OpinionLetter(TypedDict):
    id: str
    fair_use_analysis_id: str
    counsel_firm: str
    letter_reference: str
    risk_rating: str
    issued_by_user_id: str
    status: str
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubjectRelease(TypedDict):
    id: str
    production_id: str
    asset_id: Optional[str]
    subject_person_key: str
    release_type: str
    approval_rights: str
    depiction_from_date: str
    depiction_to_date: str
    revision_round_count: int
    status: str
    cut_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClearanceChart(TypedDict):
    id: str
    production_id: str
    chart_label: str
    pinned_rows: List[Dict[str, Any]]
    pinned_row_count: int
    pinned_opinion_letter_ids: List[str]
    music_leg_gap_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EOApplication(TypedDict):
    id: str
    production_id: str
    clearance_chart_id: str
    coverage_limit_cents: int
    retention_cents: int
    premium_cents: Optional[int]
    legal_review_status: str
    underwriting_review_status: str
    legal_reviewer_user_id: Optional[str]
    underwriting_reviewer_user_id: Optional[str]
    policy_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryPackage(TypedDict):
    id: str
    production_id: str
    clearance_chart_id: str
    distributor_name: str
    window_class: str
    cue_sheet_row_count: int
    rights_chart_row_count: int
    music_leg_gap_count: int
    suspension_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
