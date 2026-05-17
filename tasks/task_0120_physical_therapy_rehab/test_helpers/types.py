"""Domain types: entity TypedDicts, status enums, and the role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Patient, Episode, Evaluation, PlanOfCare, Visit, HomeExerciseProgram,
  DischargeAssessment, Therapist carry id, created_at, updated_at, and
  version. PRD §2.4: "Most resources carry an id which is a UUID string
  ..., a created_at timestamp ..., an updated_at timestamp ..., and a
  version integer that begins at 1 on creation and increments by 1
  every time the resource is mutated."

- MipsMeasure and VeteranReferral are append-only and carry ONLY id
  and created_at. PRD §2.4: "The two exceptions are append-only
  entities — MipsMeasure rows and VeteranReferral rows — which carry
  only id and created_at; their updated_at and version fields are
  absent because the platform never mutates them in place."
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    THERAPIST = "Therapist"
    BILLER = "Biller"
    PATIENT = "Patient"


# ---------------------------------------------------------------------------
# Patient — PRD §3.1.
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class InsuranceType(str, Enum):
    MEDICARE_PART_B = "MEDICARE_PART_B"
    VA = "VA"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1.
# ---------------------------------------------------------------------------
class TherapistCredential(str, Enum):
    PT = "PT"
    PTA = "PTA"
    DPT = "DPT"


class TherapistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ---------------------------------------------------------------------------
# Episode — PRD §3.2 / §3.6 / §3.9.
# ---------------------------------------------------------------------------
class EpisodeStatus(str, Enum):
    DRAFT = "DRAFT"
    EVALUATED = "EVALUATED"
    ACTIVE = "ACTIVE"
    REEVAL_DUE = "REEVAL_DUE"
    DISCHARGE_PENDING = "DISCHARGE_PENDING"
    DISCHARGED = "DISCHARGED"
    CANCELLED = "CANCELLED"


class BodyRegion(str, Enum):
    LUMBAR = "LUMBAR"
    CERVICAL = "CERVICAL"
    KNEE = "KNEE"
    SHOULDER = "SHOULDER"
    HIP = "HIP"
    ANKLE = "ANKLE"
    OTHER = "OTHER"


class CapPolicy(str, Enum):
    CAPPED = "CAPPED"
    UNCAPPED = "UNCAPPED"


class DischargeOutcome(str, Enum):
    GOALS_MET = "GOALS_MET"
    PARTIAL = "PARTIAL"
    PLATEAU = "PLATEAU"
    ADVERSE_EVENT = "ADVERSE_EVENT"
    PATIENT_WITHDREW = "PATIENT_WITHDREW"


# ---------------------------------------------------------------------------
# Evaluation — PRD §3.2.
# ---------------------------------------------------------------------------
class EvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class EvaluationType(str, Enum):
    INITIAL = "INITIAL"
    REEVAL = "REEVAL"


class EvaluationComplexity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


# ---------------------------------------------------------------------------
# PlanOfCare — PRD §3.3.
# ---------------------------------------------------------------------------
class PlanOfCareStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Authorization — PRD §3.4.
# ---------------------------------------------------------------------------
class AuthorizationStatus(str, Enum):
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuthorizationSource(str, Enum):
    COMMERCIAL_PAYER = "COMMERCIAL_PAYER"
    MEDICARE_AUTO = "MEDICARE_AUTO"
    VA_REFERRAL = "VA_REFERRAL"


# ---------------------------------------------------------------------------
# Visit — PRD §3.5.
# ---------------------------------------------------------------------------
class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    SIGNED = "SIGNED"
    BILLED = "BILLED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# HomeExerciseProgram — PRD §3.7.
# ---------------------------------------------------------------------------
class HomeExerciseProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# DischargeAssessment — PRD §3.9.
# ---------------------------------------------------------------------------
class DischargeAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


# ---------------------------------------------------------------------------
# MipsMeasure — PRD §3.8.
# ---------------------------------------------------------------------------
class MipsMeasureCode(str, Enum):
    Q126_PAIN_ASSESSMENT = "Q126_PAIN_ASSESSMENT"
    Q127_FUNCTIONAL_STATUS = "Q127_FUNCTIONAL_STATUS"
    Q128_FALL_RISK_SCREEN = "Q128_FALL_RISK_SCREEN"


class MipsExceptionReason(str, Enum):
    NONE = "NONE"
    MEDICAL = "MEDICAL"
    PATIENT = "PATIENT"
    SYSTEM = "SYSTEM"


# ---------------------------------------------------------------------------
# VeteranReferral — PRD §3.1.
# ---------------------------------------------------------------------------
class VeteranReferralStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entities with id + created_at + updated_at + version — PRD §2.4.
# ---------------------------------------------------------------------------
class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    insurance_type: str
    medicare_beneficiary_id: Optional[str]
    va_referral_id: Optional[str]
    ytd_capped_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    credential: str
    can_evaluate: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict, total=False):
    id: str
    patient_id: str
    referring_provider_npi: str
    body_region: str
    status: str
    cap_policy: Optional[str]
    kx_modifier_required: bool
    total_authorized_units: int
    total_committed_units: int
    total_reserved_units: int
    discharge_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    id: str
    episode_id: str
    evaluation_type: str
    clinician_id: str
    complexity: str
    functional_baseline_score: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanOfCare(TypedDict, total=False):
    id: str
    episode_id: str
    evaluation_id: str
    certifying_physician_npi: str
    planned_visit_count: int
    planned_units_per_visit: int
    cert_period_start: str
    cert_period_end: str
    status: str
    capped_projection_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    episode_id: str
    plan_of_care_id: str
    authorization_id: str
    clinician_id: str
    scheduled_start: str
    scheduled_end: str
    units_planned: int
    timed_minutes: int
    units_billed: int
    charge_cents: int
    kx_applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class HomeExerciseProgram(TypedDict, total=False):
    id: str
    episode_id: str
    plan_of_care_id: str
    prescribing_clinician_id: str
    exercise_items: List[Dict[str, Any]]
    patient_acknowledged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DischargeAssessment(TypedDict, total=False):
    id: str
    episode_id: str
    discharging_clinician_id: str
    discharge_outcome: str
    final_functional_score: int
    functional_delta: Optional[int]
    mips_quality_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only (PRD §2.4).
# ---------------------------------------------------------------------------
class Authorization(TypedDict, total=False):
    id: str
    episode_id: str
    plan_of_care_id: str
    source: str
    external_reference: str
    unit_quota: int
    valid_from: str
    valid_through: str
    status: str
    created_at: str


class MipsMeasure(TypedDict, total=False):
    id: str
    episode_id: str
    measure_code: str
    visit_id: str
    numerator_met: bool
    exception_reason: str
    scored_at: str
    created_at: str


class VeteranReferral(TypedDict, total=False):
    id: str
    patient_id: str
    referring_va_facility_code: str
    authorized_units: int
    valid_from: str
    valid_through: str
    status: str
    created_at: str


# ---------------------------------------------------------------------------
# Cap status read response — PRD §2.8.
# ---------------------------------------------------------------------------
class CapStatus(TypedDict, total=False):
    ytd_capped_amount_cents: int
    remaining_to_threshold_cents: int
    remaining_to_hard_cap_cents: int
    kx_required: bool


__all__ = [
    # Role enum
    "UserRole",
    # Status / enum types
    "PatientStatus",
    "InsuranceType",
    "TherapistCredential",
    "TherapistStatus",
    "EpisodeStatus",
    "BodyRegion",
    "CapPolicy",
    "DischargeOutcome",
    "EvaluationStatus",
    "EvaluationType",
    "EvaluationComplexity",
    "PlanOfCareStatus",
    "AuthorizationStatus",
    "AuthorizationSource",
    "VisitStatus",
    "HomeExerciseProgramStatus",
    "DischargeAssessmentStatus",
    "MipsMeasureCode",
    "MipsExceptionReason",
    "VeteranReferralStatus",
    # Entity TypedDicts
    "Patient",
    "Therapist",
    "Episode",
    "Evaluation",
    "PlanOfCare",
    "Visit",
    "HomeExerciseProgram",
    "DischargeAssessment",
    "Authorization",
    "MipsMeasure",
    "VeteranReferral",
    "CapStatus",
]
