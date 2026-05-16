"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.5 distinguishes two common-fields shapes:

- Patient, InsurancePolicy, Encounter, ChargeItem, and CodingRecord
  carry id, created_at, updated_at, and version. PRD §2.5: "The Patient,
  InsurancePolicy, Encounter, ChargeItem, and CodingRecord resources
  additionally carry an updated_at ISO 8601 UTC timestamp that is
  refreshed on every mutation of the resource, and an integer version
  that begins at 1 on creation and is incremented by exactly one on
  each subsequent mutation."

- ClearanceDecision, PatientPayment, and BadDebtRecord are append-only
  audit records. PRD §2.5: "The ClearanceDecision, PatientPayment, and
  BadDebtRecord resources are immutable audit records once written.
  They carry id and created_at but they do not carry updated_at and
  they do not carry version."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    REGISTRATION_CLERK = "RegistrationClerk"
    CHARGE_CAPTURE_CLERK = "ChargeCaptureClerk"
    CODER = "Coder"
    BILLER = "Biller"
    TEST_HARNESS = "TestHarness"


# ---------------------------------------------------------------------------
# Patient status — PRD §3.1
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# InsurancePolicy status — PRD §3.1
# ---------------------------------------------------------------------------
class InsurancePolicyStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


# ---------------------------------------------------------------------------
# Encounter status — PRD §3.2
# ---------------------------------------------------------------------------
class EncounterStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ELIGIBILITY_VERIFIED = "ELIGIBILITY_VERIFIED"
    CHARGES_CAPTURED = "CHARGES_CAPTURED"
    CODED = "CODED"
    CLEARED = "CLEARED"
    BILLED = "BILLED"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# ChargeItem status — PRD §3.4
# ---------------------------------------------------------------------------
class ChargeItemStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# CodingRecord status — PRD §3.6
# ---------------------------------------------------------------------------
class CodingRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# ClearanceDecision decision — PRD §3.6
# ---------------------------------------------------------------------------
class ClearanceDecisionValue(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# PatientPayment method — PRD §3.7
# ---------------------------------------------------------------------------
class PatientPaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    CHECK = "CHECK"
    REFUND = "REFUND"


# ---------------------------------------------------------------------------
# Entities with id + created_at + updated_at + version — PRD §2.5
# ---------------------------------------------------------------------------
class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    patient_id: str
    payer_name: str
    policy_number: str
    plan_year: int
    deductible_cents: int
    deductible_met_cents: int
    coinsurance_rate_bps: int
    oop_max_cents: int
    oop_accumulated_cents: int
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    patient_id: str
    policy_id: str
    admission_at: str
    discharge_at: Optional[str]
    billed_at: Optional[str]
    status: str
    total_charges_cents: int
    payer_responsibility_cents: int
    patient_responsibility_cents: int
    estimated_patient_responsibility_cents: int
    write_off_cents: int
    outstanding_balance_cents: int
    overpayment_cents: int
    created_at: str
    updated_at: str
    version: int


class ChargeItem(TypedDict, total=False):
    id: str
    encounter_id: str
    cpt_code: str
    description: str
    quantity: int
    unit_price_cents: int
    amount_cents: int
    status: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CodingRecord(TypedDict, total=False):
    id: str
    encounter_id: str
    primary_icd10: str
    secondary_icd10: List[str]
    cpt_codes: List[str]
    coder_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only. PRD §2.5: "they do not
# carry updated_at and they do not carry version."
# ---------------------------------------------------------------------------
class ClearanceDecision(TypedDict, total=False):
    id: str
    encounter_id: str
    decision: str
    allowed_amount_cents: int
    denial_reason_code: Optional[str]
    decided_at: str
    created_at: str


class PatientPayment(TypedDict, total=False):
    id: str
    encounter_id: str
    amount_cents: int
    method: str
    posted_at: str
    created_at: str


class BadDebtRecord(TypedDict, total=False):
    id: str
    encounter_id: str
    write_off_cents: int
    days_since_billed: int
    written_off_at: str
    created_at: str


__all__ = [
    "UserRole",
    "PatientStatus",
    "InsurancePolicyStatus",
    "EncounterStatus",
    "ChargeItemStatus",
    "CodingRecordStatus",
    "ClearanceDecisionValue",
    "PatientPaymentMethod",
    "Patient",
    "InsurancePolicy",
    "Encounter",
    "ChargeItem",
    "CodingRecord",
    "ClearanceDecision",
    "PatientPayment",
    "BadDebtRecord",
]
