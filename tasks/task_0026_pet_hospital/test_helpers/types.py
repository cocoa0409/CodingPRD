"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes pinned to PRD §2.4 and §3 prose. Entities that PRD §2.4
explicitly excludes from optimistic concurrency (VaccineSchedule,
VaccinationRecord, AuditLog) carry only id and created_at; their
TypedDicts MUST omit updated_at and version because the contract tells
the implementer not to emit those keys.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TRIAGE_NURSE = "TriageNurse"
    DRAFTING_VET = "DraftingVet"
    REVIEWING_VET = "ReviewingVet"
    PHARMACIST = "Pharmacist"
    CASHIER = "Cashier"
    OWNER_SERVICE = "OwnerService"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3 narratives)
# ---------------------------------------------------------------------------
class VisitStatus(str, Enum):
    REGISTERED = "REGISTERED"
    TRIAGED = "TRIAGED"
    IN_CONSULT = "IN_CONSULT"
    CONSULT_DONE = "CONSULT_DONE"
    HOSPITALIZED = "HOSPITALIZED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TriagePriority(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class DepartmentCode(str, Enum):
    INTERNAL_MED = "INTERNAL_MED"
    SURGERY = "SURGERY"
    EMERGENCY = "EMERGENCY"
    DERMATOLOGY = "DERMATOLOGY"
    DENTAL = "DENTAL"


class TreatmentRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class LabReportStatus(str, Enum):
    ORDERED = "ORDERED"
    SAMPLE_COLLECTED = "SAMPLE_COLLECTED"
    SENT_TO_LAB = "SENT_TO_LAB"
    RESULT_RECEIVED = "RESULT_RECEIVED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    DISPENSED = "DISPENSED"
    CANCELLED = "CANCELLED"


class InteractionRisk(str, Enum):
    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class HospitalizationStatus(str, Enum):
    ADMITTED = "ADMITTED"
    IN_CARE = "IN_CARE"
    DISCHARGE_PENDING = "DISCHARGE_PENDING"
    DISCHARGED = "DISCHARGED"
    CANCELLED = "CANCELLED"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class WardCode(str, Enum):
    ISOLATION = "ISOLATION"
    GENERAL = "GENERAL"
    ICU = "ICU"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    RABBIT = "RABBIT"
    BIRD = "BIRD"
    OTHER = "OTHER"


class VaccinationRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALLED = "RECALLED"
    SUPERSEDED = "SUPERSEDED"


class LineItemKind(str, Enum):
    CONSULT = "CONSULT"
    LAB = "LAB"
    DRUG = "DRUG"
    HOSPITAL_DAY = "HOSPITAL_DAY"


class AuditAction(str, Enum):
    DRAFT = "DRAFT"
    SUBMIT = "SUBMIT"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DISPENSE = "DISPENSE"
    FINALIZE = "FINALIZE"
    AMEND = "AMEND"
    CANCEL = "CANCEL"


class AuditSubjectType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    TREATMENT_RECORD = "TREATMENT_RECORD"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true → id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class Owner(TypedDict, total=False):
    id: str
    full_name: str
    phone_e164: str
    email: str
    contact_verified: bool
    deposit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict, total=False):
    id: str
    owner_id: str
    name: str
    species: str
    birth_date: str
    weight_kg: float
    medical_history: List[Any]
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    pet_id: str
    symptom_text: str
    severity_score: int
    triage_priority: Optional[str]
    department_code: Optional[str]
    assigned_vet_id: Optional[str]
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentRecord(TypedDict, total=False):
    id: str
    visit_id: str
    consultation_notes: str
    diagnosis_code: str
    treatment_plan: str
    consent_recorded: bool
    consent_recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LabReport(TypedDict, total=False):
    id: str
    visit_id: str
    test_items: List[Any]
    sample_collected_at: Optional[str]
    external_lab_ref: Optional[str]
    results: List[Any]
    abnormal_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Drug(TypedDict, total=False):
    id: str
    code: str
    name: str
    controlled: bool
    dosage_min_mg_per_kg: float
    dosage_max_mg_per_kg: float
    interactions: List[Any]
    stock_units: int
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    visit_id: str
    drafting_vet_id: str
    reviewing_vet_id: Optional[str]
    items: List[Any]
    interaction_risk: str
    status: str
    rejection_reason: Optional[str]
    dispensed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cage(TypedDict, total=False):
    id: str
    cage_code: str
    ward_code: str
    capacity: int
    occupancy_count: int
    created_at: str
    updated_at: str
    version: int


class Hospitalization(TypedDict, total=False):
    id: str
    visit_id: str
    cage_id: str
    admitted_at: str
    discharged_at: Optional[str]
    daily_care_log: List[Any]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict, total=False):
    id: str
    visit_id: str
    line_items: List[Any]
    package_code: Optional[str]
    deposit_applied_cents: int
    insurance_estimate_cents: int
    insurance_actual_cents: int
    provisional_total_cents: int
    final_total_cents: int
    paid_amount_cents: int
    refund_amount_cents: int
    invoice_no: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Bare entities (PRD §2.4: no updated_at, no version).
# ---------------------------------------------------------------------------
class VaccineSchedule(TypedDict, total=False):
    id: str
    species: str
    vaccine_code: str
    age_min_days: int
    booster_interval_days: Optional[int]
    required: bool
    created_at: str


class VaccinationRecord(TypedDict, total=False):
    id: str
    pet_id: str
    vaccine_code: str
    administered_at: str
    batch_id: str
    status: str
    next_due_at: Optional[str]
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    action: str
    from_state: Optional[str]
    to_state: str
    payload_hash: str
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "VisitStatus",
    "TriagePriority",
    "DepartmentCode",
    "TreatmentRecordStatus",
    "LabReportStatus",
    "PrescriptionStatus",
    "InteractionRisk",
    "HospitalizationStatus",
    "BillStatus",
    "WardCode",
    "Species",
    "VaccinationRecordStatus",
    "LineItemKind",
    "AuditAction",
    "AuditSubjectType",
    "Owner",
    "Pet",
    "Visit",
    "TreatmentRecord",
    "LabReport",
    "Drug",
    "Prescription",
    "Cage",
    "Hospitalization",
    "Bill",
    "VaccineSchedule",
    "VaccinationRecord",
    "AuditLog",
]
