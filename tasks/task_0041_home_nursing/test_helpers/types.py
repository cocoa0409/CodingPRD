"""Domain types for the Home Nursing API.

Status enums and entity TypedDicts derived from PRD §2.4 (resource identity)
and PRD §3 entity prose.

PRD §2.4 distinguishes two field-shape classes:

- Standard resources (Nurse, ServiceItem, Order, ServiceRecord, Package,
  Settlement, Complaint) carry id, created_at, updated_at, version.

- Append-only entries (CertificationRecord, Dispatch, WasteEntry, AuditLog,
  PayoutBatch) carry only id and created_at -- tests MUST NOT assert
  updated_at or version on these.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PATIENT = "Patient"
    NURSE = "Nurse"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class NurseCertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    EXPIRING = "EXPIRING"
    DISQUALIFIED = "DISQUALIFIED"


class CertificationKind(str, Enum):
    INITIAL = "INITIAL"
    RECERTIFICATION = "RECERTIFICATION"
    TRAINING = "TRAINING"
    DISQUALIFICATION = "DISQUALIFICATION"


class CertificationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Gender(str, Enum):
    M = "M"
    F = "F"
    O = "O"


class PreferredGender(str, Enum):
    M = "M"
    F = "F"
    ANY = "ANY"


class SkillTag(str, Enum):
    WOUND_CARE = "WOUND_CARE"
    IV_INFUSION = "IV_INFUSION"
    CATHETER_CARE = "CATHETER_CARE"
    MATERNAL_NEWBORN = "MATERNAL_NEWBORN"
    ELDERLY_CARE = "ELDERLY_CARE"
    PALLIATIVE = "PALLIATIVE"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWAITING_DISPATCH = "AWAITING_DISPATCH"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class DispatchStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ServiceRecordStatus(str, Enum):
    STARTED = "STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PATIENT_CONFIRM = "AWAITING_PATIENT_CONFIRM"
    COMPLETED = "COMPLETED"


class WasteCategory(str, Enum):
    SHARPS = "SHARPS"
    INFECTIOUS = "INFECTIOUS"
    PHARMACEUTICAL = "PHARMACEUTICAL"


class WasteUnit(str, Enum):
    PCS = "PCS"
    LITERS = "LITERS"
    KG = "KG"


class WasteStatus(str, Enum):
    REGISTERED = "REGISTERED"
    HANDED_OVER = "HANDED_OVER"
    ARCHIVED = "ARCHIVED"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    FINALIZED = "FINALIZED"
    PAID_OUT = "PAID_OUT"
    REVERSED = "REVERSED"


class ComplaintCategory(str, Enum):
    NURSE_MISCONDUCT = "NURSE_MISCONDUCT"
    SERVICE_QUALITY = "SERVICE_QUALITY"
    BILLING = "BILLING"
    SAFETY = "SAFETY"
    OTHER = "OTHER"


class ComplaintRouting(str, Enum):
    NURSE_RELATED = "NURSE_RELATED"
    SERVICE_RELATED = "SERVICE_RELATED"


class ComplaintStage(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGE = "TRIAGE"
    MEDIATION = "MEDIATION"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class PayoutBatchStatus(str, Enum):
    BUILDING = "BUILDING"
    PAID = "PAID"


class VitalType(str, Enum):
    BP = "BP"
    HR = "HR"
    TEMP = "TEMP"
    SPO2 = "SPO2"
    GLU = "GLU"


class AbnormalSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AuditSubjectType(str, Enum):
    ORDER = "ORDER"
    SERVICE_RECORD = "SERVICE_RECORD"
    COMPLAINT = "COMPLAINT"
    NURSE = "NURSE"


# ---------------------------------------------------------------------------
# Standard resources (PRD §2.4 -- carry id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Nurse(TypedDict, total=False):
    id: str
    full_name: str
    gender: str
    languages: List[str]
    license_number: str
    license_verified: bool
    hospital_affiliation_verified: bool
    specialty_tags: List[str]
    home_lat: float
    home_lng: float
    max_daily_orders: int
    revenue_share_bps: int
    rating: float
    certification_status: str
    certified_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceItem(TypedDict, total=False):
    id: str
    code: str
    name: str
    description: str
    contraindications: str
    required_skill: str
    requires_medical_doc: bool
    requires_eligibility_review: bool
    base_price_cents: int
    duration_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    patient_id: str
    service_item_code: str
    service_address: str
    service_lat: float
    service_lng: float
    scheduled_start: str
    preferred_gender: str
    preferred_language: str
    medical_doc_url: Optional[str]
    package_id: Optional[str]
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    status: str
    payment_status: str
    cancelled_reason: Optional[str]
    dispatch_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceRecord(TypedDict, total=False):
    id: str
    order_id: str
    nurse_id: str
    checkin_at: str
    checkin_lat: float
    checkin_lng: float
    face_verification_passed: bool
    checklist_items: List[Dict[str, Any]]
    vitals: List[Dict[str, Any]]
    medications_administered: List[Dict[str, Any]]
    evidence_urls: List[str]
    abnormal_events: List[Dict[str, Any]]
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict, total=False):
    id: str
    patient_id: str
    service_item_code: str
    total_credits: int
    used_credits: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    order_id: str
    gross_fee_cents: int
    distance_surcharge_cents: int
    time_of_day_surcharge_cents: int
    package_deduction_cents: int
    refund_cents: int
    tax_cents: int
    nurse_revenue_share_cents: int
    platform_share_cents: int
    payout_batch_id: Optional[str]
    status: str
    created_at: str


class Complaint(TypedDict, total=False):
    id: str
    order_id: str
    nurse_id: str
    patient_id: str
    category: str
    routing: Optional[str]
    description: str
    stage: str
    rating_impact: float
    compensation_cents: int
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only resources (PRD §2.4 -- only id and created_at)
# ---------------------------------------------------------------------------
class CertificationRecord(TypedDict, total=False):
    id: str
    nurse_id: str
    kind: str
    training_hours: float
    outcome: str
    effective_at: str
    notes: Optional[str]
    created_at: str


class Dispatch(TypedDict, total=False):
    id: str
    order_id: str
    nurse_id: str
    ranked_score: float
    distance_km: float
    offered_at: str
    accept_deadline: str
    status: str
    rejection_reason: Optional[str]
    created_at: str


class WasteEntry(TypedDict, total=False):
    id: str
    order_id: str
    category: str
    quantity: float
    unit: str
    sealed: bool
    disposal_unit_id: Optional[str]
    handover_at: Optional[str]
    certificate_url: Optional[str]
    status: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_id: str
    action: str
    payload: Dict[str, Any]
    created_at: str


class PayoutBatch(TypedDict, total=False):
    id: str
    cutoff_at: str
    total_settlements: int
    total_nurse_share_cents: int
    total_platform_share_cents: int
    status: str
    created_at: str


__all__ = [
    "UserRole",
    "NurseCertificationStatus",
    "CertificationKind",
    "CertificationOutcome",
    "Gender",
    "PreferredGender",
    "SkillTag",
    "OrderStatus",
    "PaymentStatus",
    "DispatchStatus",
    "ServiceRecordStatus",
    "WasteCategory",
    "WasteUnit",
    "WasteStatus",
    "PackageStatus",
    "SettlementStatus",
    "ComplaintCategory",
    "ComplaintRouting",
    "ComplaintStage",
    "PayoutBatchStatus",
    "VitalType",
    "AbnormalSeverity",
    "AuditSubjectType",
    "Nurse",
    "ServiceItem",
    "Order",
    "ServiceRecord",
    "Package",
    "Settlement",
    "Complaint",
    "CertificationRecord",
    "Dispatch",
    "WasteEntry",
    "AuditLog",
    "PayoutBatch",
]
