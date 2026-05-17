"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Patient, Clinician, OASISAssessment, Episode, Visit, and PDGMClaim
  carry id, created_at, updated_at, and version. PRD §2.4: "Every
  primary resource — Patient, Clinician, OASISAssessment, Episode,
  Visit, and PDGMClaim — carries a system-managed id (UUID string, no
  type prefix), a created_at ISO 8601 UTC timestamp with three
  fractional digits indicating when it was first written, an updated_at
  ISO 8601 UTC timestamp refreshed on any subsequent mutation, and a
  version integer that begins at 1 and increases by exactly 1 every
  time the resource is mutated."

- MileageLog is append-only — PRD §2.4: "MileageLog is immutable once
  recorded; the row carries id and created_at but does not carry
  updated_at and does not carry version — both fields are absent from
  the JSON response."

- ClockState is a singleton without standard common fields — PRD §2.4:
  "The ClockState singleton is purely a test-driving lever: it carries
  no id, no created_at, no updated_at, and no version. Its sole exposed
  attribute is current_date."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    FIELD_CLINICIAN = "FieldClinician"
    BILLING_SPECIALIST = "BillingSpecialist"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Clinician — PRD §3.2
# ---------------------------------------------------------------------------
class ClinicianDiscipline(str, Enum):
    SN = "SN"
    PT = "PT"
    OT = "OT"
    SLP = "SLP"
    HHA = "HHA"


class ClinicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# OASISAssessment — PRD §3.3
# ---------------------------------------------------------------------------
class OASISAssessmentReason(str, Enum):
    START_OF_CARE = "START_OF_CARE"
    RECERTIFICATION = "RECERTIFICATION"
    RESUMPTION_OF_CARE = "RESUMPTION_OF_CARE"


class OASISClinicalGrouping(str, Enum):
    MMTA_OTHER = "MMTA_OTHER"
    NEURO = "NEURO"
    WOUND = "WOUND"
    MS_REHAB = "MS_REHAB"
    BEHAVIORAL = "BEHAVIORAL"
    COMPLEX = "COMPLEX"


class OASISFunctionalImpairmentLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OASISAdmissionSource(str, Enum):
    COMMUNITY = "COMMUNITY"
    INSTITUTIONAL = "INSTITUTIONAL"


class OASISStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Episode — PRD §3.4
# ---------------------------------------------------------------------------
class EpisodeType(str, Enum):
    INITIAL = "INITIAL"
    RECERT = "RECERT"
    ROC = "ROC"


class EpisodeTimingCategory(str, Enum):
    EARLY = "EARLY"
    LATE = "LATE"


class EpisodeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Visit — PRD §3.5
# ---------------------------------------------------------------------------
class VisitType(str, Enum):
    SN = "SN"
    PT = "PT"
    OT = "OT"
    SLP = "SLP"
    HHA = "HHA"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# PDGMClaim — PRD §3.7
# ---------------------------------------------------------------------------
class PDGMClaimStatus(str, Enum):
    PENDING = "PENDING"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# Entities with id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------
class Patient(TypedDict, total=False):
    id: str
    full_name: str
    medicare_id: str
    home_zip: str
    wage_index: float
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict, total=False):
    id: str
    full_name: str
    discipline: str
    license_expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OASISAssessment(TypedDict, total=False):
    id: str
    patient_id: str
    assessment_reason: str
    assessment_date: str
    clinical_grouping: str
    functional_impairment_level: str
    admission_source: str
    hha_companion_hours_ordered: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict, total=False):
    id: str
    patient_id: str
    source_oasis_id: str
    episode_type: str
    start_date: str
    end_date: str
    timing_category: str
    recert_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    episode_id: str
    clinician_id: str
    visit_type: str
    visit_date: str
    start_minute: int
    end_minute: int
    hha_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PDGMClaim(TypedDict, total=False):
    id: str
    episode_id: str
    hipps_code: str
    case_mix_weight: float
    provisional_payment: float
    final_payment: Optional[float]
    lupa_applied: Optional[bool]
    total_mileage_reimbursement: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entity — id + created_at only (PRD §2.4)
# ---------------------------------------------------------------------------
class MileageLog(TypedDict, total=False):
    id: str
    visit_id: str
    episode_id: str
    miles_driven: float
    reimbursement_amount: float
    created_at: str


# ---------------------------------------------------------------------------
# ClockState singleton — no common fields (PRD §2.4)
# ---------------------------------------------------------------------------
class ClockState(TypedDict, total=False):
    current_date: str


__all__ = [
    "UserRole",
    "ClinicianDiscipline",
    "ClinicianStatus",
    "OASISAssessmentReason",
    "OASISClinicalGrouping",
    "OASISFunctionalImpairmentLevel",
    "OASISAdmissionSource",
    "OASISStatus",
    "EpisodeType",
    "EpisodeTimingCategory",
    "EpisodeStatus",
    "VisitType",
    "VisitStatus",
    "PDGMClaimStatus",
    "Patient",
    "Clinician",
    "OASISAssessment",
    "Episode",
    "Visit",
    "PDGMClaim",
    "MileageLog",
    "ClockState",
]
