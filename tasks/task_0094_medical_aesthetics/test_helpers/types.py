"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4, most resources carry id/created_at/updated_at/version.
OperativeRecord, PaymentEvent, AuditEntry, and SyncEvent are
append-only — they carry only id and created_at; no updated_at and no
version on those entities.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MEDICAL_DIRECTOR = "MedicalDirector"
    CONSULTANT = "Consultant"
    ATTENDING_PHYSICIAN = "AttendingPhysician"
    SENIOR_PHYSICIAN = "SeniorPhysician"
    NURSE = "Nurse"
    FINANCE_OFFICER = "FinanceOfficer"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Project (PRD §3.1)
# ---------------------------------------------------------------------------
class ProjectCategory(str, Enum):
    SURGICAL = "SURGICAL"
    NON_SURGICAL = "NON_SURGICAL"
    SKINCARE = "SKINCARE"


class ProjectRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    ON_SHELF = "ON_SHELF"
    OFF_SHELF = "OFF_SHELF"


# ---------------------------------------------------------------------------
# ConsumableSku (PRD §3.1)
# ---------------------------------------------------------------------------
class SkuKind(str, Enum):
    CONSUMABLE = "CONSUMABLE"
    DRUG = "DRUG"


# ---------------------------------------------------------------------------
# Room (PRD §3.1)
# ---------------------------------------------------------------------------
class RoomKind(str, Enum):
    SURGICAL_OR = "SURGICAL_OR"
    PROCEDURE = "PROCEDURE"
    TREATMENT = "TREATMENT"


# ---------------------------------------------------------------------------
# Customer (PRD §3.2)
# ---------------------------------------------------------------------------
class KycStatus(str, Enum):
    NOT_VERIFIED = "NOT_VERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# ContraindicationRule (PRD §3.1)
# ---------------------------------------------------------------------------
class ContraindicationSeverity(str, Enum):
    ABSOLUTE = "ABSOLUTE"
    RELATIVE = "RELATIVE"


# ---------------------------------------------------------------------------
# TreatmentPlan (PRD §3.3)
# ---------------------------------------------------------------------------
class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Appointment (PRD §3.4)
# ---------------------------------------------------------------------------
class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# ---------------------------------------------------------------------------
# FollowUp (PRD §3.6)
# ---------------------------------------------------------------------------
class FollowUpStage(str, Enum):
    D1 = "D1"
    W1 = "W1"
    M1 = "M1"
    M3 = "M3"


class FollowUpStatus(str, Enum):
    PENDING = "PENDING"
    REMINDED = "REMINDED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class FollowUpChannel(str, Enum):
    CALL = "CALL"
    IM = "IM"


# ---------------------------------------------------------------------------
# AdverseEvent (PRD §3.6)
# ---------------------------------------------------------------------------
class AdverseEventSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AdverseEventStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# InstallmentPlan (PRD §3.7)
# ---------------------------------------------------------------------------
class InstallmentPlanStatus(str, Enum):
    PENDING_KYC = "PENDING_KYC"
    ACTIVE = "ACTIVE"
    IN_DEFAULT = "IN_DEFAULT"
    REFUNDED = "REFUNDED"
    COMPLETED = "COMPLETED"


class PaymentEventKind(str, Enum):
    INSTALLMENT_PAID = "INSTALLMENT_PAID"
    PREPAYMENT = "PREPAYMENT"
    REFUND = "REFUND"
    COLLECTION_NOTICE = "COLLECTION_NOTICE"


# ---------------------------------------------------------------------------
# SyncEvent topics/kinds (PRD §2.9, §3.*)
# ---------------------------------------------------------------------------
class SyncTopic(str, Enum):
    PAYMENT = "PAYMENT"
    FINANCE_PARTNER = "FINANCE_PARTNER"
    IM = "IM"
    PHARMA_TRACE = "PHARMA_TRACE"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true → id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Project(TypedDict, total=False):
    id: str
    code: str
    name: str
    category: str
    technique: str
    duration_minutes: int
    recovery_days: int
    risk_level: str
    bom: List[dict]
    qualified_doctor_ids: List[str]
    pricing_tiers: List[dict]
    status: str
    reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsumableSku(TypedDict, total=False):
    id: str
    sku_code: str
    name: str
    kind: str
    requires_lot_tracking: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    contact_phone: str
    medical_history: List[str]
    allergies: List[str]
    medication_history: List[str]
    health_declaration: dict
    photo_archive_ids: List[str]
    scan3d_archive_ids: List[str]
    kyc_status: str
    credit_score: Optional[int]
    risk_score: float
    adverse_event_count: int
    created_at: str
    updated_at: str
    version: int


class ContraindicationRule(TypedDict, total=False):
    id: str
    project_id: str
    severity: str
    predicate: dict
    reason: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict, total=False):
    id: str
    customer_id: str
    consultant_id: str
    items: List[dict]
    expected_outcome: str
    risk_disclosure: str
    requires_senior_countersign: bool
    attending_physician_id: Optional[str]
    senior_physician_id: Optional[str]
    provisional_total_cents: int
    final_total_cents: Optional[int]
    status: str
    plan_version: int
    locked_project_versions: Optional[dict]
    informed_consent_signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    plan_id: str
    project_id: str
    scheduled_start: str
    scheduled_end: str
    prep_window_start: str
    doctor_id: str
    nurse_id: str
    room_id: str
    equipment_ids: List[str]
    anesthesia_resource_id: Optional[str]
    status: str
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    code: str
    room_kind: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class FollowUp(TypedDict, total=False):
    id: str
    appointment_id: str
    stage: str
    due_at: str
    channel: str
    status: str
    feedback: Optional[dict]
    adverse_event_filed: bool
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict, total=False):
    id: str
    appointment_id: str
    customer_id: str
    severity: str
    description: str
    status: str
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallmentPlan(TypedDict, total=False):
    id: str
    treatment_plan_id: str
    principal_cents: int
    downpayment_cents: int
    term_months: int
    apr_bps: Optional[int]
    finance_partner_id: str
    schedule: List[dict]
    paid_amount_cents: int
    status: str
    default_strike_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only TypedDicts — id + created_at ONLY (common_fields: false)
# Per PRD §2.4, these MUST NOT carry updated_at or version.
# ---------------------------------------------------------------------------
class OperativeRecord(TypedDict, total=False):
    id: str
    appointment_id: str
    check_in_at: str
    procedure_log: List[dict]
    consumable_usage: List[dict]
    vital_sign_attachments: List[str]
    incidents: List[dict]
    post_photo_ids: List[str]
    created_at: str


class PaymentEvent(TypedDict, total=False):
    id: str
    installment_plan_id: str
    kind: str
    amount_cents: int
    external_ref: str
    recorded_at: str
    created_at: str


class AuditEntry(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    subject_type: str
    subject_id: str
    payload: dict
    created_at: str


class SyncEvent(TypedDict, total=False):
    id: str
    topic: str
    kind: str
    payload: dict
    emitted_at: str
    created_at: str
