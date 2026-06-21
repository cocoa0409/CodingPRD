"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the standard system-managed fields
(id, created_at, updated_at, version), so every TypedDict includes them.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ────────────────────────────────────────────────────────
class ResidencyStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    RESIDENT = "RESIDENT"
    NONRESIDENT = "NONRESIDENT"


class ResidencyVerificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ResultingResidency(str, Enum):
    RESIDENT = "RESIDENT"
    NONRESIDENT = "NONRESIDENT"


class EducationCertificateStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ProductKind(str, Enum):
    LICENSE = "LICENSE"
    TAG = "TAG"
    STAMP = "STAMP"


class ResidencyRestriction(str, Enum):
    ANY = "ANY"
    RESIDENT_ONLY = "RESIDENT_ONLY"
    NONRESIDENT_ONLY = "NONRESIDENT_ONLY"


class LicenseProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SpeciesSeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ScoringModel(str, Enum):
    SQUARED = "SQUARED"
    LINEAR = "LINEAR"


class DrawPoolStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    CLOSED = "CLOSED"
    DRAWN = "DRAWN"


class DrawApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    UNSUCCESSFUL = "UNSUCCESSFUL"
    WITHDRAWN = "WITHDRAWN"


class IssuedVia(str, Enum):
    OVER_THE_COUNTER = "OVER_THE_COUNTER"
    DRAW_AWARD = "DRAW_AWARD"


class LicenseStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class HarvestReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReplacementReason(str, Enum):
    LOST = "LOST"
    DAMAGED = "DAMAGED"
    STOLEN = "STOLEN"


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    LICENSE_AGENT = "LicenseAgent"
    DRAW_OFFICER = "DrawOfficer"
    GAME_WARDEN = "GameWarden"


# ─── Entity TypedDicts (all common_fields: true) ─────────────────────────
class Applicant(TypedDict):
    id: str
    full_name: str
    birth_date: str
    declared_state_code: str
    residency_status: str
    education_certified: bool
    preference_points: int
    bonus_points: int
    created_at: str
    updated_at: str
    version: int


class ResidencyVerification(TypedDict):
    id: str
    applicant_id: str
    proof_type: str
    proof_state_code: str
    continuous_months: int
    status: str
    resulting_residency: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationCertificate(TypedDict):
    id: str
    applicant_id: str
    course_code: str
    completion_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseProduct(TypedDict):
    id: str
    sku: str
    product_kind: str
    species_season_id: Optional[str]
    requires_education: bool
    residency_restriction: str
    base_fee_cents: int
    min_age_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpeciesSeason(TypedDict):
    id: str
    species: str
    season_open: str
    season_close: str
    bag_limit: int
    draw_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawPool(TypedDict):
    id: str
    species_season_id: str
    license_product_id: str
    quota: int
    scoring_model: str
    status: str
    awarded_count: int
    entry_deadline: str
    created_at: str
    updated_at: str
    version: int


class DrawApplication(TypedDict):
    id: str
    draw_pool_id: str
    applicant_id: str
    points_at_entry: int
    bonus_at_entry: int
    priority_score: int
    status: str
    issued_license_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    applicant_id: str
    license_product_id: str
    draw_application_id: Optional[str]
    issued_via: str
    fee_charged_cents: int
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HarvestReport(TypedDict):
    id: str
    license_id: str
    harvest_datetime: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Replacement(TypedDict):
    id: str
    original_license_id: str
    reason: str
    replacement_license_id: Optional[str]
    admin_fee_cents: int
    created_at: str
    updated_at: str
    version: int
