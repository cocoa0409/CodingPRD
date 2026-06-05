"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource definitions and status lifecycles. Generic
envelope types are provided by the framework and are not redefined here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────
class UserRole(str, Enum):
    UNOS_ADMIN = "UNOSAdmin"
    TRANSPLANT_CENTER = "TransplantCenter"
    ORGAN_PROCUREMENT_ORG = "OrganProcurementOrg"


# ─── Enumerations ──────────────────────────────────────────────────────
class OrganType(str, Enum):
    LIVER = "LIVER"
    KIDNEY = "KIDNEY"
    HEART = "HEART"
    LUNG = "LUNG"


class BloodType(str, Enum):
    O = "O"
    A = "A"
    B = "B"
    AB = "AB"


class CandidateListingStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    TRANSPLANTED = "TRANSPLANTED"
    REMOVED = "REMOVED"


class CandidateMedicalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RemovalReason(str, Enum):
    TRANSPLANTED = "TRANSPLANTED"
    DECEASED = "DECEASED"
    IMPROVED = "IMPROVED"
    TRANSFERRED = "TRANSFERRED"
    OTHER = "OTHER"


class ClinicalScoreStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class ScoreKind(str, Enum):
    MELD_NA = "MELD_NA"
    PELD = "PELD"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class DonorOrganStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MATCHING = "MATCHING"
    ALLOCATED = "ALLOCATED"
    TRANSPLANTED = "TRANSPLANTED"
    DISCARDED = "DISCARDED"


class MatchRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


class PolicyCode(str, Enum):
    STANDARD = "STANDARD"
    BROADER_SHARING = "BROADER_SHARING"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class DeclineReason(str, Enum):
    SIZE_MISMATCH = "SIZE_MISMATCH"
    MEDICAL_UNSUITABLE = "MEDICAL_UNSUITABLE"
    CANDIDATE_UNAVAILABLE = "CANDIDATE_UNAVAILABLE"
    CENTER_DECLINE = "CENTER_DECLINE"
    OTHER = "OTHER"


class GraftStatus(str, Enum):
    FUNCTIONING = "FUNCTIONING"
    AT_RISK = "AT_RISK"
    FAILED = "FAILED"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class IntervalLabel(str, Enum):
    M1 = "M1"
    M6 = "M6"
    M12 = "M12"
    M24 = "M24"


class ReportKind(str, Enum):
    TRANSPLANT = "TRANSPLANT"
    REMOVAL = "REMOVAL"
    FOLLOWUP = "FOLLOWUP"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# Full-common-field entities carry id, created_at, updated_at, version.

class TransplantCenter(TypedDict):
    id: str
    name: str
    unos_center_code: str
    region_code: int
    latitude: float
    longitude: float
    created_at: str
    updated_at: str
    version: int


class OrganProcurementOrg(TypedDict):
    id: str
    name: str
    opo_code: str
    region_code: int
    latitude: float
    longitude: float
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    center_id: str
    mrn: str
    organ_type: str
    blood_type: str
    date_of_birth: str
    height_cm: float
    weight_kg: float
    hla_a: List[str]
    hla_b: List[str]
    hla_dr: List[str]
    unacceptable_antigens: List[str]
    listing_status: str
    medical_status: str
    current_meld_peld: int
    is_pediatric: bool
    listed_at: Optional[str]
    waiting_time_days: int
    removal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClinicalScore(TypedDict):
    id: str
    candidate_id: str
    bilirubin_mg_dl: float
    inr: float
    creatinine_mg_dl: float
    sodium_mmol_l: float
    albumin_g_dl: float
    growth_failure: bool
    on_dialysis_twice_in_week: bool
    effective_at: str
    score_kind: Optional[str]
    raw_score: Optional[float]
    allocation_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistRegistration(TypedDict):
    id: str
    candidate_id: str
    organ_type: str
    status: str
    suspended_at: Optional[str]
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorOrgan(TypedDict):
    id: str
    opo_id: str
    organ_type: str
    blood_type: str
    donor_height_cm: float
    donor_weight_kg: float
    hla_a: List[str]
    hla_b: List[str]
    hla_dr: List[str]
    recovered_at: str
    max_cold_ischemia_hours: float
    status: str
    open_offer_count: int
    created_at: str
    updated_at: str
    version: int


class MatchRun(TypedDict):
    id: str
    donor_organ_id: str
    policy_code: str
    ranked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ranking row: carries ONLY id + created_at (no updated_at/version).
class MatchListEntry(TypedDict):
    id: str
    match_run_id: str
    candidate_id: str
    rank: int
    priority_points: float
    hla_mismatch_count: int
    created_at: str


class Offer(TypedDict):
    id: str
    donor_organ_id: str
    candidate_id: str
    match_run_id: str
    rank_at_offer: int
    offered_at: str
    response_deadline_at: str
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transplant(TypedDict):
    id: str
    offer_id: str
    candidate_id: str
    donor_organ_id: str
    transplanted_at: str
    cold_ischemia_hours_actual: float
    graft_status: str
    created_at: str
    updated_at: str
    version: int


class FollowUp(TypedDict):
    id: str
    transplant_id: str
    interval_label: str
    scheduled_for: str
    graft_functioning: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class UnosReport(TypedDict):
    id: str
    report_kind: str
    transplant_id: Optional[str]
    candidate_id: Optional[str]
    submitted_at: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Singleton clock: exposes only current_utc.
class SystemClock(TypedDict):
    current_utc: str
