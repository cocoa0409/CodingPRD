"""Domain types: entity TypedDicts, status enums, and the role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Patient, Provider, Encounter, Prescription, Referral, PortalMessage
  carry id, created_at, updated_at, and version. PRD §2.4: "Most primary
  resources — Patient, Provider, Encounter, Prescription, Referral, and
  PortalMessage — carry a common set of system-managed fields: id,
  created_at, updated_at, version."

- CptLineItem, CptFeeCatalog, HedisMeasurement, and AuditLog are
  append-only and carry ONLY id (or cpt_code as primary key) and
  created_at (or computed_at / occurred_at). PRD §2.4: "Three entities
  deliberately do not carry the full common-field set: CptLineItem,
  CptFeeCatalog, and HedisMeasurement each carry only an id (the
  CptFeeCatalog instead uses cpt_code as its primary key in place of id)
  and a created_at (or, for HedisMeasurement, the equivalent
  computed_at snapshot timestamp). These three entities do not carry
  updated_at and do not carry version; supplying or expecting a version
  on them is a contract error. AuditLog likewise carries no updated_at
  or version."
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PATIENT_PORTAL_USER = "PatientPortalUser"
    PROVIDER = "Provider"
    NURSE = "Nurse"
    RECEPTIONIST = "Receptionist"
    BILLING_CLERK = "BillingClerk"
    PHARMACIST = "Pharmacist"
    CLINIC_ADMIN = "ClinicAdmin"
    TEST_HARNESS = "TestHarness"


# ---------------------------------------------------------------------------
# Patient — PRD §3.1.
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SexAtBirth(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNKNOWN = "UNKNOWN"


class SmokingStatus(str, Enum):
    NEVER = "NEVER"
    FORMER = "FORMER"
    CURRENT = "CURRENT"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Provider — PRD §3.2.
# ---------------------------------------------------------------------------
class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProviderRoleType(str, Enum):
    PCP_ONLY = "PCP_ONLY"
    SPECIALIST_ONLY = "SPECIALIST_ONLY"
    BOTH = "BOTH"


# ---------------------------------------------------------------------------
# Encounter — PRD §3.3.
# ---------------------------------------------------------------------------
class EncounterStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class EncounterType(str, Enum):
    CONSULTATION = "CONSULTATION"
    PHYSICAL = "PHYSICAL"
    VACCINATION = "VACCINATION"


# ---------------------------------------------------------------------------
# Prescription — PRD §3.4.
# ---------------------------------------------------------------------------
class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    TRANSMITTED = "TRANSMITTED"
    DISPENSED = "DISPENSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DeaSchedule(str, Enum):
    II = "II"
    III = "III"
    IV = "IV"
    V = "V"


# ---------------------------------------------------------------------------
# Referral — PRD §3.5.
# ---------------------------------------------------------------------------
class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class ReferralPriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


# ---------------------------------------------------------------------------
# PortalMessage — PRD §3.6 — two parallel dimensions.
# ---------------------------------------------------------------------------
class PortalMessageStatus(str, Enum):
    UNREAD = "UNREAD"
    READ = "READ"
    ARCHIVED = "ARCHIVED"


class PortalMessageTriageStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"


class PortalMessageSenderRole(str, Enum):
    PATIENT = "PATIENT"
    PROVIDER = "PROVIDER"


# ---------------------------------------------------------------------------
# HEDIS — PRD §3.8.
# ---------------------------------------------------------------------------
class HedisMeasureId(str, Enum):
    AWV = "AWV"
    CBP = "CBP"
    TSC = "TSC"
    CCS = "CCS"


# ---------------------------------------------------------------------------
# Entities with id + created_at + updated_at + version — PRD §2.4.
# ---------------------------------------------------------------------------
class Patient(TypedDict, total=False):
    id: str
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: str
    sex_at_birth: str
    pcp_provider_id: Optional[str]
    pcp_bound_at: Optional[str]
    portal_enabled: bool
    smoking_status: str
    chronic_conditions: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    full_name: str
    role_type: str
    specialty: Optional[str]
    dea_number: Optional[str]
    epcs_enrolled: bool
    panel_size: int
    panel_cap: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: str
    encounter_type: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    chief_complaint: Optional[str]
    vital_signs: Optional[Dict[str, Any]]
    bmi: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: str
    encounter_id: str
    drug_name: str
    rxnorm_code: str
    is_controlled: bool
    dea_schedule: Optional[str]
    dose_mg: float
    quantity: int
    refills_authorized: int
    refills_remaining: Optional[int]
    epcs_two_factor_token: Optional[str]
    status: str
    signed_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    patient_id: str
    referring_provider_id: str
    referred_to_provider_id: str
    encounter_id: str
    reason: str
    priority: str
    status: str
    accepted_at: Optional[str]
    expires_at: str
    response_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PortalMessage(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: str
    sender_role: str
    body: str
    status: str
    triage_status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only (PRD §2.4).
# ---------------------------------------------------------------------------
class CptLineItem(TypedDict, total=False):
    id: str
    encounter_id: str
    cpt_code: str
    units: int
    list_charge_cents: int
    allowed_amount_cents: Optional[int]
    modifier: Optional[str]
    is_preventive: bool
    created_at: str


class CptFeeCatalog(TypedDict, total=False):
    cpt_code: str
    description: str
    list_price_cents: int
    allowed_price_cents: int
    is_preventive: bool
    is_telehealth_eligible: bool
    created_at: str


class HedisMeasurement(TypedDict, total=False):
    id: str
    patient_id: str
    measure_id: str
    measurement_year: int
    in_denominator: bool
    in_numerator: bool
    computed_at: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    target_entity: str
    target_id: str
    epcs_signature_hash: Optional[str]
    occurred_at: str
    created_at: str


__all__ = [
    # Role enum
    "UserRole",
    # Status / enum types
    "PatientStatus",
    "SexAtBirth",
    "SmokingStatus",
    "ProviderStatus",
    "ProviderRoleType",
    "EncounterStatus",
    "EncounterType",
    "PrescriptionStatus",
    "DeaSchedule",
    "ReferralStatus",
    "ReferralPriority",
    "PortalMessageStatus",
    "PortalMessageTriageStatus",
    "PortalMessageSenderRole",
    "HedisMeasureId",
    # Entity TypedDicts
    "Patient",
    "Provider",
    "Encounter",
    "Prescription",
    "Referral",
    "PortalMessage",
    "CptLineItem",
    "CptFeeCatalog",
    "HedisMeasurement",
    "AuditLog",
]
