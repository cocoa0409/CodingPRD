"""Domain types for the Citizen Science Data Collection API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    VOLUNTEER = "Volunteer"
    EXPERT = "Expert"
    RESEARCH_PARTNER = "ResearchPartner"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CertificationLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class EquipmentType(str, Enum):
    NONE = "NONE"
    ACOUSTIC_RECORDER = "ACOUSTIC_RECORDER"
    GPS_LOGGER = "GPS_LOGGER"
    SPOTTING_SCOPE = "SPOTTING_SCOPE"


class VolunteerStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class RecognitionTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ExpertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CertificationStatus(str, Enum):
    ENROLLED = "ENROLLED"
    TRAINED = "TRAINED"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SuspendedReason(str, Enum):
    NONE = "NONE"
    QUALITY_PROBATION = "QUALITY_PROBATION"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class HabitatType(str, Enum):
    WETLAND = "WETLAND"
    FOREST = "FOREST"
    GRASSLAND = "GRASSLAND"
    URBAN = "URBAN"
    COASTAL = "COASTAL"


class CoverageStatus(str, Enum):
    GAP = "GAP"
    UNDER = "UNDER"
    MET = "MET"
    SATURATED = "SATURATED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RETRACTED = "RETRACTED"


class PublicationDimension(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    QUEUED = "QUEUED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class PhotoStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    FLAGGED_MISMATCH = "FLAGGED_MISMATCH"
    REJECTED = "REJECTED"


class VoteDecision(str, Enum):
    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LOAN = "ON_LOAN"
    QUARANTINE = "QUARANTINE"
    IN_CALIBRATION = "IN_CALIBRATION"
    RETIRED = "RETIRED"


class LoanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class ConditionOnReturn(str, Enum):
    NONE = "NONE"
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    EMBARGOED = "EMBARGOED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class PartnerStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class TrustTier(str, Enum):
    STANDARD = "STANDARD"
    TRUSTED = "TRUSTED"


class GrantScope(str, Enum):
    AGGREGATE = "AGGREGATE"
    FULL = "FULL"
    SENSITIVE = "SENSITIVE"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class DeniedReason(str, Enum):
    NONE = "NONE"
    PUBLICATION_WITHDRAWN = "PUBLICATION_WITHDRAWN"
    GRANT_EXPIRED = "GRANT_EXPIRED"
    ADMIN_REVOKED = "ADMIN_REVOKED"


class AwardType(str, Enum):
    OBSERVATION_ACCEPTED = "OBSERVATION_ACCEPTED"
    STREAK_BONUS = "STREAK_BONUS"
    MILESTONE = "MILESTONE"
    REVERSAL = "REVERSAL"


# --- Entities carrying id + created_at + updated_at + version ---

class Protocol(TypedDict):
    id: str
    code: str
    title: str
    version_number: int
    supersedes_protocol_id: Optional[str]
    status: str
    required_certification_level: str
    min_photo_count: int
    max_submission_lag_hours: int
    required_equipment_type: str
    certification_valid_days: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    home_region_code: str
    status: str
    quality_score: float
    lifetime_quality_score: float
    recognition_tier: str
    lifetime_points: int
    accepted_observation_count: int
    rejected_observation_count: int
    consecutive_accepted: int
    consecutive_rejections: int
    created_at: str
    updated_at: str
    version: int


class Expert(TypedDict):
    id: str
    full_name: str
    specialty_taxon: str
    verification_weight: float
    linked_volunteer_id: Optional[str]
    status: str
    vote_count: int
    retracted_confirm_count: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    volunteer_id: str
    protocol_id: str
    trainer_expert_id: str
    level: str
    status: str
    exam_score: Optional[int]
    granted_at: Optional[str]
    expires_at: Optional[str]
    suspended_reason: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    name: str
    protocol_id: str
    season_start_date: str
    season_end_date: str
    status: str
    target_observations_per_site: int
    coverage_score: float
    gap_count: int
    site_count: int
    accepted_observation_count: int
    created_at: str
    updated_at: str
    version: int


class SurveySite(TypedDict):
    id: str
    campaign_id: str
    site_code: str
    latitude: float
    longitude: float
    habitat_type: str
    priority_weight: float
    accepted_observation_count: int
    coverage_ratio: float
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class Observation(TypedDict):
    id: str
    campaign_id: str
    site_id: str
    volunteer_id: str
    equipment_loan_id: Optional[str]
    publication_id: Optional[str]
    observed_at: str
    submitted_at: str
    latitude: float
    longitude: float
    species_code: str
    count_value: int
    photo_count: int
    review_status: str
    publication_status: str
    revision_round: int
    provisional_quality_points: float
    final_quality_points: float
    consensus_confidence: float
    confirm_weight: float
    reject_weight: float
    revision_weight: float
    created_at: str
    updated_at: str
    version: int


class PhotoEvidence(TypedDict):
    id: str
    observation_id: str
    file_hash: str
    captured_at: str
    exif_latitude: float
    exif_longitude: float
    geo_delta_meters: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    asset_tag: str
    equipment_type: str
    status: str
    calibration_valid_until: str
    calibration_drift_ppm: float
    quarantine_until: Optional[str]
    total_loan_hours: int
    created_at: str
    updated_at: str
    version: int


class EquipmentLoan(TypedDict):
    id: str
    equipment_id: str
    volunteer_id: str
    start_at: str
    due_at: str
    issued_at: Optional[str]
    returned_at: Optional[str]
    status: str
    condition_on_return: str
    loan_hours: int
    drift_added_ppm: float
    created_at: str
    updated_at: str
    version: int


class DataPublication(TypedDict):
    id: str
    campaign_id: str
    supersedes_publication_id: Optional[str]
    doi: str
    status: str
    embargo_until: Optional[str]
    quality_floor: float
    record_count: int
    mean_quality: float
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResearchPartner(TypedDict):
    id: str
    org_name: str
    contact_email: str
    status: str
    data_use_agreement_signed_at: Optional[str]
    trust_tier: str
    active_grant_count: int
    created_at: str
    updated_at: str
    version: int


class PartnerAccessGrant(TypedDict):
    id: str
    publication_id: str
    partner_id: str
    scope: str
    status: str
    expires_at: str
    denied_reason: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger rows: id + created_at only ---

class VerificationVote(TypedDict):
    id: str
    observation_id: str
    expert_id: str
    round_number: int
    decision: str
    confidence: int
    weight_applied: float
    comment: Optional[str]
    created_at: str


class RecognitionAward(TypedDict):
    id: str
    volunteer_id: str
    observation_id: Optional[str]
    award_type: str
    points_awarded: int
    reason: str
    created_at: str
