"""Domain types: entity TypedDicts, status enums, and the role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Therapist, StateLicense, Supervisor, Patient, InsurancePlan, Appointment,
  Session, SafetyPlan, BillingClaim carry id, created_at, updated_at, and
  version. PRD §2.4: "Every resource created by this API carries a
  server-minted id ... Resources that are mutated after creation
  additionally carry updated_at ... and an integer version that begins
  at 1 and increments by exactly 1 on every successful mutation."

- SupervisionAssignment and CrisisAssessment are append-only and carry
  ONLY id and created_at — no updated_at and no version. PRD §2.4:
  "Two of the entities in this domain are append-only and therefore
  carry only id and created_at, with no updated_at and no version
  field: the SupervisionAssignment ... and the CrisisAssessment ..."
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    THERAPIST = "Therapist"
    SUPERVISOR = "Supervisor"
    BILLING_CLERK = "BillingClerk"


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1 / §3.2.
# ---------------------------------------------------------------------------
class TherapistCredentialStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class SupervisionTrack(str, Enum):
    PRE_LICENSED = "PRE_LICENSED"
    LICENSED = "LICENSED"


# ---------------------------------------------------------------------------
# StateLicense — PRD §3.1.
# ---------------------------------------------------------------------------
class StateLicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# SupervisionAssignment — PRD §3.3.
# ---------------------------------------------------------------------------
class SupervisionAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# InsurancePlan — PRD §3.5.
# ---------------------------------------------------------------------------
class NetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ContractMode(str, Enum):
    DEDUCTIBLE_FIRST = "DEDUCTIBLE_FIRST"
    COPAY_ONLY = "COPAY_ONLY"


# ---------------------------------------------------------------------------
# Appointment — PRD §3.6.
# ---------------------------------------------------------------------------
class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AppointmentHoldReason(str, Enum):
    SAFETY_PLAN_MISSING = "SAFETY_PLAN_MISSING"
    LICENSE_GAP = "LICENSE_GAP"


class CptCode(str, Enum):
    INTAKE_90791 = "90791"
    INDIVIDUAL_90834 = "90834"


class Modality(str, Enum):
    IN_PERSON = "IN_PERSON"
    TELEHEALTH = "TELEHEALTH"


# ---------------------------------------------------------------------------
# Session — PRD §3.7.
# ---------------------------------------------------------------------------
class SessionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class SessionType(str, Enum):
    INTAKE = "INTAKE"
    INDIVIDUAL = "INDIVIDUAL"


# ---------------------------------------------------------------------------
# CrisisAssessment / SafetyPlan — PRD §3.9.
# ---------------------------------------------------------------------------
class CrisisRiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class SafetyPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RESCINDED = "RESCINDED"


# ---------------------------------------------------------------------------
# BillingClaim — PRD §3.7 / §3.8.
# ---------------------------------------------------------------------------
class BillingMode(str, Enum):
    INSURANCE_IN_NETWORK = "INSURANCE_IN_NETWORK"
    SELF_PAY = "SELF_PAY"


class BillingClaimStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version — PRD §2.4.
# ---------------------------------------------------------------------------
class Therapist(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    credential_status: str
    supervision_track: str
    supervision_hours_accrued: float
    licensure_exam_eligible: bool
    psypact_enrolled: bool
    pricing_rack_90791_cents: int
    pricing_rack_90834_cents: int
    created_at: str
    updated_at: str
    version: int


class StateLicense(TypedDict, total=False):
    id: str
    therapist_id: str
    state_code: str
    license_number: str
    status: str
    issued_on: str
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class Supervisor(TypedDict, total=False):
    id: str
    full_name: str
    home_state_code: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    state_of_residence: str
    household_income_cents: int
    household_size: int
    sliding_fee_tier_pct: int
    insurance_plan_id: Optional[str]
    deductible_remaining_cents: int
    latest_crisis_level: Optional[str]
    safety_plan_required: bool
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict, total=False):
    id: str
    payer_name: str
    plan_code: str
    network_status: str
    contract_mode: str
    allowed_amount_90791_cents: int
    allowed_amount_90834_cents: int
    copay_cents: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    therapist_id: str
    patient_id: str
    cpt_code: str
    modality: str
    patient_state_on_day: str
    scheduled_start: str
    scheduled_end: str
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    appointment_id: str
    type: str
    actual_duration_minutes: int
    supervision_credit_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyPlan(TypedDict, total=False):
    id: str
    patient_id: str
    trigger_assessment_id: str
    warning_signs: str
    coping_strategies: str
    support_contacts: List[Dict[str, str]]
    crisis_hotline: str
    means_restriction_plan: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingClaim(TypedDict, total=False):
    id: str
    appointment_id: str
    patient_id: str
    insurance_plan_id: Optional[str]
    cpt_code: str
    billing_mode: str
    charged_amount_cents: int
    patient_responsibility_cents: int
    insurer_paid_cents: int
    status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only (PRD §2.4).
# ---------------------------------------------------------------------------
class SupervisionAssignment(TypedDict, total=False):
    id: str
    therapist_id: str
    supervisor_id: str
    started_on: str
    ended_on: Optional[str]
    status: str
    created_at: str


class CrisisAssessment(TypedDict, total=False):
    id: str
    patient_id: str
    therapist_id: str
    si_score: int
    pa_score: int
    su_score: int
    so_score: int
    am_score: int
    composite_score: float
    risk_level: str
    assessed_at: str
    created_at: str


__all__ = [
    "UserRole",
    "TherapistCredentialStatus",
    "SupervisionTrack",
    "StateLicenseStatus",
    "SupervisionAssignmentStatus",
    "NetworkStatus",
    "ContractMode",
    "AppointmentStatus",
    "AppointmentHoldReason",
    "CptCode",
    "Modality",
    "SessionStatus",
    "SessionType",
    "CrisisRiskLevel",
    "SafetyPlanStatus",
    "BillingMode",
    "BillingClaimStatus",
    "Therapist",
    "StateLicense",
    "Supervisor",
    "Patient",
    "InsurancePlan",
    "Appointment",
    "Session",
    "SafetyPlan",
    "BillingClaim",
    "SupervisionAssignment",
    "CrisisAssessment",
]
