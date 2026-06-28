"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycle states described in the PRD. Versioned
entities carry id/created_at/updated_at/version; the two append-only records
(HealthMarkerResult, MarkerCatalogEntry) carry only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class PetStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ARCHIVED = "ARCHIVED"


class KitStatus(str, Enum):
    ORDERED = "ORDERED"
    ACTIVATED = "ACTIVATED"
    RECEIVED = "RECEIVED"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"


class SampleStatus(str, Enum):
    RECEIVED = "RECEIVED"
    GENOTYPING = "GENOTYPING"
    PASS = "PASS"
    QNS = "QNS"
    FAILED = "FAILED"
    RETESTED = "RETESTED"


class GenotypingOutcome(str, Enum):
    PASS = "PASS"
    QNS = "QNS"
    FAILED = "FAILED"


class ReportStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINALIZED = "FINALIZED"
    REVOKED = "REVOKED"


class MarkerGenotype(str, Enum):
    CLEAR = "CLEAR"
    CARRIER = "CARRIER"
    AT_RISK = "AT_RISK"


class MarkerReviewStatus(str, Enum):
    PASS = "PASS"
    REVIEWED = "REVIEWED"


class RelativeMatchStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class ShareLinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class DataRequestStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    GRACE = "GRACE"
    PURGING = "PURGING"
    PURGED = "PURGED"
    CANCELLED = "CANCELLED"


class DataRequestKind(str, Enum):
    DOWNLOAD = "DOWNLOAD"
    DELETE = "DELETE"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class DataResidency(str, Enum):
    US = "US"
    EU = "EU"


class ProductTier(str, Enum):
    BREED = "BREED"
    BREED_HEALTH = "BREED_HEALTH"


class MarkerCategory(str, Enum):
    HEALTH = "HEALTH"
    TRAIT = "TRAIT"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT = "Account"
    LAB_TECHNICIAN = "LabTechnician"
    VETERINARIAN = "Veterinarian"
    ANONYMOUS = "Anonymous"


# --- Versioned entity TypedDicts (id + created_at + updated_at + version) ---

class Account(TypedDict):
    id: str
    email: str
    full_name: str
    data_residency: str
    active_subscription_id: Optional[str]
    relative_finder_opt_in: bool
    pet_count: int
    purge_pending: bool
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict):
    id: str
    account_id: str
    name: str
    species: str
    birth_year: int
    relative_finder_opt_in: bool
    status: str
    finalized_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Kit(TypedDict):
    id: str
    account_id: str
    barcode: str
    product_tier: str
    status: str
    activated_pet_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict):
    id: str
    kit_id: str
    pet_id: Optional[str]
    status: str
    qc_score: Optional[float]
    retest_of_sample_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GenotypingRun(TypedDict):
    id: str
    sample_id: str
    call_rate: float
    het_rate: float
    contamination: float
    qc_score: Optional[float]
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    sample_id: str
    pet_id: str
    includes_health: bool
    status: str
    breed_composition: list
    at_risk_marker_count: int
    created_at: str
    updated_at: str
    version: int


class RelativeMatch(TypedDict):
    id: str
    pet_id: str
    relative_pet_id: str
    shared_cm: float
    relationship_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareLink(TypedDict):
    id: str
    report_id: str
    vet_email: str
    token: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    tier: str
    status: str
    started_on: str
    term_days: int
    annual_fee_cents: int
    last_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class DataRequest(TypedDict):
    id: str
    account_id: str
    kind: str
    status: str
    grace_until: Optional[str]
    export_payload: Optional[dict]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (id + created_at only; NO updated_at, NO version) ---

class HealthMarkerResult(TypedDict):
    id: str
    report_id: str
    marker_code: str
    genotype: str
    review_status: str
    created_at: str


class MarkerCatalogEntry(TypedDict):
    id: str
    marker_code: str
    category: str
    species: str
    created_at: str
