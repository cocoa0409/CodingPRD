"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Clinic, Patient, DiagnosticEvaluation, TreatmentPlan, Authorization,
  Therapist, TherapySession, and InsuranceClaim each carry id,
  created_at, updated_at, and version. PRD §2.4: "Most entities — Clinic,
  Patient, DiagnosticEvaluation, TreatmentPlan, Authorization, Therapist,
  TherapySession, and InsuranceClaim — additionally carry updated_at …
  and version (a non-negative integer initialised to 1 at creation and
  incremented by exactly one on each state-changing mutation)."

- BillingLedgerEntry is the single append-only exception. PRD §2.4:
  "The append-only BillingLedgerEntry is the single exception: each
  entry carries only id and created_at — it has no updated_at and no
  version, because ledger rows are immutable once written."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BCBA = "BCBA"
    RBT = "RBT"
    CLINIC_ADMIN = "ClinicAdmin"
    PAYER_ADMIN = "PayerAdmin"


# ---------------------------------------------------------------------------
# Patient status — PRD §3.1
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


# ---------------------------------------------------------------------------
# Therapist credential / status — PRD §3.1
# ---------------------------------------------------------------------------
class TherapistCredential(str, Enum):
    BCBA = "BCBA"
    RBT = "RBT"


class TherapistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# DiagnosticEvaluation — PRD §3.2
# ---------------------------------------------------------------------------
class DiagnosticEvaluationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VOID = "VOID"


class SeverityLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


# ---------------------------------------------------------------------------
# TreatmentPlan — PRD §3.3
# ---------------------------------------------------------------------------
class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Authorization — PRD §3.4
# ---------------------------------------------------------------------------
class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"
    DENIED = "DENIED"


class CptCode(str, Enum):
    EVAL = "97151"
    DIRECT_RBT = "97153"
    BCBA_SUPERVISION = "97155"
    PARENT_TRAINING = "97156"


# ---------------------------------------------------------------------------
# TherapySession — PRD §3.5
# ---------------------------------------------------------------------------
class TherapySessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BILLED = "BILLED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class SessionType(str, Enum):
    DIRECT_RBT = "DIRECT_RBT"
    BCBA_SUPERVISION = "BCBA_SUPERVISION"
    PARENT_TRAINING = "PARENT_TRAINING"


# ---------------------------------------------------------------------------
# InsuranceClaim — PRD §3.6
# ---------------------------------------------------------------------------
class InsuranceClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class DenialReason(str, Enum):
    SUPERVISION_RATIO_BREACH = "SUPERVISION_RATIO_BREACH"
    UNITS_OUT_OF_AUTH = "UNITS_OUT_OF_AUTH"
    MISSING_PROGRESS_NOTE = "MISSING_PROGRESS_NOTE"
    DUPLICATE_LINE = "DUPLICATE_LINE"


# ---------------------------------------------------------------------------
# BillingLedgerEntry — PRD §2.11
# ---------------------------------------------------------------------------
class LedgerEntryType(str, Enum):
    PROVISIONAL_DEBIT = "PROVISIONAL_DEBIT"
    PROVISIONAL_CREDIT = "PROVISIONAL_CREDIT"
    ADJUDICATED_DEBIT = "ADJUDICATED_DEBIT"
    ADJUDICATED_CREDIT = "ADJUDICATED_CREDIT"


class LedgerReasonCode(str, Enum):
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_CANCELLED = "SESSION_CANCELLED"
    SESSION_DISPUTED = "SESSION_DISPUTED"
    CLAIM_PAID = "CLAIM_PAID"
    CLAIM_DENIED = "CLAIM_DENIED"
    CLAIM_APPEAL_PAID = "CLAIM_APPEAL_PAID"


# ===========================================================================
# Entities with id + created_at + updated_at + version (PRD §2.4)
# ===========================================================================
class Clinic(TypedDict, total=False):
    id: str
    name: str
    now_ts: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    clinic_id: str
    legal_name: str
    date_of_birth: str
    insurance_member_id: str
    clinical_progress_score_provisional: float
    clinical_progress_score_adjudicated: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict, total=False):
    id: str
    clinic_id: str
    legal_name: str
    credential: str
    license_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiagnosticEvaluation(TypedDict, total=False):
    id: str
    patient_id: str
    evaluator_therapist_id: str
    scheduled_at: str
    completed_at: Optional[str]
    diagnosis_code: Optional[str]
    severity_level: Optional[str]
    recommended_weekly_hours: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict, total=False):
    id: str
    patient_id: str
    source_evaluation_id: str
    weekly_direct_hours_target: int
    weekly_supervision_hours_target: float
    weekly_parent_training_hours_target: float
    plan_version: int
    superseded_by_id: Optional[str]
    activated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict, total=False):
    id: str
    patient_id: str
    treatment_plan_id: str
    payer_name: str
    cpt_code: str
    approved_units: int
    effective_start: str
    effective_end: str
    provisional_units_consumed: int
    adjudicated_units_consumed: int
    renewed_from_id: Optional[str]
    renewed_to_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TherapySession(TypedDict, total=False):
    id: str
    patient_id: str
    authorization_id: str
    therapist_id: str
    supervising_therapist_id: Optional[str]
    session_type: str
    planned_start: str
    planned_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    planned_units: int
    billed_units: Optional[int]
    dispute_reason: Optional[str]
    progress_rating: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    patient_id: str
    authorization_id: str
    session_ids: List[str]
    appeal_round: int
    submitted_amount_cents: int
    reimbursed_amount_cents: int
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only entity — id + created_at only (PRD §2.4)
# ===========================================================================
class BillingLedgerEntry(TypedDict, total=False):
    id: str
    authorization_id: str
    session_id: Optional[str]
    claim_id: Optional[str]
    entry_type: str
    units_delta: int
    reason_code: str
    created_at: str


__all__ = [
    "UserRole",
    "PatientStatus",
    "TherapistCredential",
    "TherapistStatus",
    "DiagnosticEvaluationStatus",
    "SeverityLevel",
    "TreatmentPlanStatus",
    "AuthorizationStatus",
    "CptCode",
    "TherapySessionStatus",
    "SessionType",
    "InsuranceClaimStatus",
    "DenialReason",
    "LedgerEntryType",
    "LedgerReasonCode",
    "Clinic",
    "Patient",
    "Therapist",
    "DiagnosticEvaluation",
    "TreatmentPlan",
    "Authorization",
    "TherapySession",
    "InsuranceClaim",
    "BillingLedgerEntry",
]
