"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Patient, VaccineProduct, VaccineLot, ProviderOrganization,
  AdministeredDose, AdverseEvent, AntigenScheduleRule, and
  SchoolEnrollmentCertificate carry id, created_at, updated_at, and
  version. PRD §2.4: "Most entities additionally carry updated_at and
  version. updated_at is refreshed every time any mutating operation
  touches the entity ... version is an integer that starts at 1 on
  creation and increments by exactly 1 on every persisted mutation,
  again including cascades."

- AllergyRecord is the single exception. PRD §2.4: "its record is
  immutable once written and therefore carries only id and created_at
  - both updated_at and version are absent from its representation."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles - PRD §2.1.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROVIDER_CLINICIAN = "ProviderClinician"
    REVIEWING_CLINICIAN = "ReviewingClinician"
    SCHOOL_REGISTRAR = "SchoolRegistrar"
    PUBLIC_HEALTH_OFFICER = "PublicHealthOfficer"


# ---------------------------------------------------------------------------
# Patient - PRD §3.1.
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"
    MERGED_OUT = "MERGED_OUT"
    ARCHIVED = "ARCHIVED"


class SexAtBirth(str, Enum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    UNKNOWN = "UNKNOWN"


class Patient(TypedDict, total=False):
    id: str
    first_name: str
    last_name: str
    date_of_birth: str
    sex_at_birth: str
    state_resident: bool
    guardian_contact_email: str
    medical_exemption_on_file: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# VaccineProduct - PRD §3.2.
# ---------------------------------------------------------------------------
class VaccineProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class Route(str, Enum):
    IM = "IM"
    SC = "SC"
    ORAL = "ORAL"
    INTRANASAL = "INTRANASAL"


class Antigen(str, Enum):
    DTAP_DIPHTHERIA = "DTAP_DIPHTHERIA"
    DTAP_TETANUS = "DTAP_TETANUS"
    DTAP_PERTUSSIS = "DTAP_PERTUSSIS"
    MMR_MEASLES = "MMR_MEASLES"
    MMR_MUMPS = "MMR_MUMPS"
    MMR_RUBELLA = "MMR_RUBELLA"
    HEPB = "HEPB"
    HPV = "HPV"
    POLIO = "POLIO"
    VARICELLA = "VARICELLA"


class AllergenCode(str, Enum):
    EGG = "EGG"
    LATEX = "LATEX"
    NEOMYCIN = "NEOMYCIN"
    GELATIN = "GELATIN"
    YEAST = "YEAST"
    OTHER = "OTHER"


class VaccineProduct(TypedDict, total=False):
    id: str
    cvx_code: str
    trade_name: str
    antigens: List[str]
    min_age_days: int
    max_age_days: Optional[int]
    route: str
    contraindication_flags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# VaccineLot - PRD §3.2.
# ---------------------------------------------------------------------------
class VaccineLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RECALLED = "RECALLED"
    EXHAUSTED = "EXHAUSTED"


class RecallReason(str, Enum):
    MANUFACTURER_DEFECT = "MANUFACTURER_DEFECT"
    CONTAMINATION = "CONTAMINATION"
    EXPIRED = "EXPIRED"


class VaccineLot(TypedDict, total=False):
    id: str
    vaccine_product_id: str
    provider_organization_id: str
    lot_number: str
    expiration_date: str
    doses_on_hand: int
    status: str
    recall_reason: Optional[str]
    recalled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# ProviderOrganization - PRD §3.2.
# ---------------------------------------------------------------------------
class ProviderOrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReportingJurisdiction(str, Enum):
    IN_STATE = "IN_STATE"
    OUT_OF_STATE = "OUT_OF_STATE"


class ProviderOrganization(TypedDict, total=False):
    id: str
    name: str
    npi: str
    reporting_jurisdiction: str
    reporting_compliance_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# AdministeredDose - PRD §3.3.
# ---------------------------------------------------------------------------
class DoseState(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADMINISTERED = "ADMINISTERED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class InvalidationReason(str, Enum):
    LOT_RECALL = "LOT_RECALL"
    DATA_ERROR = "DATA_ERROR"


class AdministeredDose(TypedDict, total=False):
    id: str
    patient_id: str
    vaccine_product_id: str
    lot_id: str
    provider_organization_id: str
    administering_clinician_id: str
    administered_at: Optional[str]
    dose_state: str
    invalidation_reason: Optional[str]
    reported_at: str
    catchup_flag: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# AllergyRecord - PRD §3.4 / §2.4 (no updated_at, no version).
# ---------------------------------------------------------------------------
class AllergySeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    ANAPHYLAXIS = "ANAPHYLAXIS"


class AllergyRecord(TypedDict, total=False):
    id: str
    patient_id: str
    allergen_code: str
    severity: str
    recorded_at: str
    created_at: str
    # No updated_at, no version - PRD §2.4: "carries only id and
    # created_at - both updated_at and version are absent."


# ---------------------------------------------------------------------------
# AdverseEvent - PRD §3.9.
# ---------------------------------------------------------------------------
class Seriousness(str, Enum):
    NON_SERIOUS = "NON_SERIOUS"
    SERIOUS = "SERIOUS"
    DEATH = "DEATH"


class ClinicalReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    CAUSALLY_RELATED = "CAUSALLY_RELATED"
    NOT_RELATED = "NOT_RELATED"


class VaersSubmissionStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    ACK_RECEIVED = "ACK_RECEIVED"
    REJECTED = "REJECTED"


class AdverseEvent(TypedDict, total=False):
    id: str
    patient_id: str
    dose_id: str
    onset_at: str
    symptom_codes: List[str]
    seriousness: str
    clinical_review_status: str
    vaers_submission_status: str
    vaers_submission_id: Optional[str]
    vaers_required: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# AntigenScheduleRule - PRD §3.7.
# ---------------------------------------------------------------------------
class AntigenScheduleRule(TypedDict, total=False):
    id: str
    antigen: str
    dose_sequence_number: int
    routine_min_age_days: int
    routine_recommended_age_days: int
    routine_max_age_days: int
    catchup_min_interval_days: int
    prerequisite_rule_id: Optional[str]
    school_enrollment_required: bool
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# SchoolEnrollmentCertificate - PRD §3.8.
# ---------------------------------------------------------------------------
class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DEFICIENT = "DEFICIENT"
    EXEMPTION_GRANTED = "EXEMPTION_GRANTED"
    REVOKED = "REVOKED"


class GradeLevel(str, Enum):
    K = "K"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"
    G9 = "G9"
    G10 = "G10"
    G11 = "G11"
    G12 = "G12"


class SchoolEnrollmentCertificate(TypedDict, total=False):
    id: str
    patient_id: str
    school_year: str
    grade_level: str
    certificate_status: str
    missing_antigens: List[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "PatientStatus",
    "SexAtBirth",
    "Patient",
    "VaccineProductStatus",
    "Route",
    "Antigen",
    "AllergenCode",
    "VaccineProduct",
    "VaccineLotStatus",
    "RecallReason",
    "VaccineLot",
    "ProviderOrganizationStatus",
    "ReportingJurisdiction",
    "ProviderOrganization",
    "DoseState",
    "InvalidationReason",
    "AdministeredDose",
    "AllergySeverity",
    "AllergyRecord",
    "Seriousness",
    "ClinicalReviewStatus",
    "VaersSubmissionStatus",
    "AdverseEvent",
    "AntigenScheduleRule",
    "CertificateStatus",
    "GradeLevel",
    "SchoolEnrollmentCertificate",
]
