"""Domain types: entity TypedDicts, status enums, role enum.

Every TypedDict mirrors the entity definition stated in PRD prose:
- Physician, StateLicense, Patient, Consult, Prescription, InsuranceClaim,
  SelfPayInvoice, FollowUp carry the full id + created_at + updated_at +
  version triplet (PRD §2.4).
- AuditEvent is append-only and carries ONLY id + created_at; it omits
  updated_at and version (PRD §2.4).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PHYSICIAN = "Physician"
    PAYER = "Payer"


# ---------------------------------------------------------------------------
# Status enums — PRD §3.1, §3.3, §3.4, §3.7
# ---------------------------------------------------------------------------
class PhysicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StateLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LicenseType(str, Enum):
    FULL = "FULL"
    IMLC_EXPEDITED = "IMLC_EXPEDITED"


class BillingMode(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"


class VisitTier(str, Enum):
    BRIEF = "BRIEF"
    STANDARD = "STANDARD"
    EXTENDED = "EXTENDED"


class RoutingBasis(str, Enum):
    FULL_LICENSE = "FULL_LICENSE"
    IMLC_EXPEDITED = "IMLC_EXPEDITED"


class ConsultStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ROUTED = "ROUTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"


class DEASchedule(str, Enum):
    NONE = "NONE"
    II = "II"
    III = "III"
    IV = "IV"
    V = "V"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    TRANSMITTED = "TRANSMITTED"
    DISPENSED = "DISPENSED"
    VOIDED = "VOIDED"


class InsuranceClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    PAID = "PAID"


class SelfPayInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class AuditEventType(str, Enum):
    CONSULT_ROUTED = "CONSULT_ROUTED"
    RX_ISSUED = "RX_ISSUED"
    RX_VOIDED = "RX_VOIDED"
    CLAIM_PAID = "CLAIM_PAID"
    LICENSE_REVOKED = "LICENSE_REVOKED"
    COMPLIANCE_FAILURE = "COMPLIANCE_FAILURE"
    CLOCK_ADVANCED = "CLOCK_ADVANCED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — PRD §2.4 + §3.x
#
# Physician, StateLicense, Patient, Consult, Prescription, InsuranceClaim,
# SelfPayInvoice, FollowUp all carry the full id/created_at/updated_at/version
# quartet per PRD §2.4. AuditEvent is append-only and carries only id +
# created_at.
# ---------------------------------------------------------------------------
class Physician(TypedDict, total=False):
    id: str
    full_name: str
    npi_number: str
    imlc_compact_member: bool
    imlc_home_state: Optional[str]
    dea_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StateLicense(TypedDict, total=False):
    id: str
    physician_id: str
    state_code: str
    license_number: str
    license_type: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    home_state_code: str
    present_state_code: str
    insurance_payer_id: Optional[str]
    insurance_member_id: Optional[str]
    insurance_deductible_remaining_cents: int
    insurance_copay_cents: int
    insurance_coinsurance_bps: int
    created_at: str
    updated_at: str
    version: int


class Consult(TypedDict, total=False):
    id: str
    patient_id: str
    physician_id: Optional[str]
    present_state_code: str
    billing_mode: str
    visit_tier: str
    routing_basis: Optional[str]
    requires_followup: bool
    base_charge_cents: Optional[int]
    final_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    consult_id: str
    prescribing_physician_id: str
    drug_name: str
    dea_schedule: str
    days_supply: int
    refills: int
    epcs_two_factor_token: Optional[str]
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    consult_id: str
    billed_cents: int
    deductible_applied_cents: int
    copay_applied_cents: int
    coinsurance_applied_cents: int
    payer_paid_cents: int
    patient_responsibility_cents: int
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelfPayInvoice(TypedDict, total=False):
    id: str
    consult_id: str
    subtotal_cents: int
    discount_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUp(TypedDict, total=False):
    id: str
    consult_id: str
    due_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


# AuditEvent is append-only — PRD §2.4: it carries id + created_at only.
class AuditEvent(TypedDict, total=False):
    id: str
    event_type: str
    subject_entity: str
    subject_id: str
    actor_role: str
    payload_json: dict
    created_at: str


__all__ = [
    "UserRole",
    "PhysicianStatus",
    "StateLicenseStatus",
    "LicenseType",
    "BillingMode",
    "VisitTier",
    "RoutingBasis",
    "ConsultStatus",
    "DEASchedule",
    "PrescriptionStatus",
    "InsuranceClaimStatus",
    "SelfPayInvoiceStatus",
    "FollowUpStatus",
    "AuditEventType",
    "Physician",
    "StateLicense",
    "Patient",
    "Consult",
    "Prescription",
    "InsuranceClaim",
    "SelfPayInvoice",
    "FollowUp",
    "AuditEvent",
]
