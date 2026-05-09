"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: top-level resources carry id, created_at, updated_at, version.
AuditLog, ExternalEvent, and PrescriberDenylistEntry are append-only — they
carry only id and created_at.
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, List, Optional, Any


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VENDOR_ADMIN = "VendorAdmin"
    PRESCRIPTION_REVIEWER = "PrescriptionReviewer"
    PHARMACIST_RE_REVIEWER = "PharmacistReReviewer"
    PHARMACIST = "Pharmacist"
    CUSTOMER = "Customer"
    REGULATORY_GATEWAY = "RegulatoryGateway"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.1–§3.8)
# ---------------------------------------------------------------------------

class DrugStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ON_SHELF = "ON_SHELF"
    OFF_SHELF = "OFF_SHELF"


class DrugClassification(str, Enum):
    OTC = "OTC"
    PRESCRIPTION = "PRESCRIPTION"


class ControlCategory(str, Enum):
    NONE = "NONE"
    NARCOTIC = "NARCOTIC"
    PSYCHOTROPIC_I = "PSYCHOTROPIC_I"
    PSYCHOTROPIC_II = "PSYCHOTROPIC_II"
    TOXIC = "TOXIC"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SUSPENDED = "SUSPENDED"


class PharmacistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class PrescriptionStatus(str, Enum):
    UPLOADED = "UPLOADED"
    REVIEW_PENDING = "REVIEW_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    ARCHIVED = "ARCHIVED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderDispensingStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PHARMACIST_REVIEWING = "PHARMACIST_REVIEWING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPENSED = "DISPENSED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PharmacistReviewStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUEST_CHANGE = "REQUEST_CHANGE"


class ColdChainShipmentStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DISPOSED = "DISPOSED"


class ADRStatus(str, Enum):
    REPORTED = "REPORTED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FOLLOW_UP_PENDING = "FOLLOW_UP_PENDING"
    ARCHIVED = "ARCHIVED"


class ADRSeverity(str, Enum):
    NON_SERIOUS = "NON_SERIOUS"
    SERIOUS = "SERIOUS"


class ADRReporterKind(str, Enum):
    PATIENT = "PATIENT"
    PHARMACIST = "PHARMACIST"


class SpecialPopulation(str, Enum):
    PREGNANCY = "PREGNANCY"
    MINOR = "MINOR"
    RENAL_FAILURE = "RENAL_FAILURE"
    GERIATRIC = "GERIATRIC"


class AuditAction(str, Enum):
    PRESCRIPTION_APPROVED = "PRESCRIPTION_APPROVED"
    PRESCRIPTION_REJECTED = "PRESCRIPTION_REJECTED"
    PRESCRIPTION_REVOKED = "PRESCRIPTION_REVOKED"
    PHARMACIST_REVIEW_APPROVED = "PHARMACIST_REVIEW_APPROVED"
    PHARMACIST_REVIEW_REJECTED = "PHARMACIST_REVIEW_REJECTED"
    PHARMACIST_REVIEW_REQUEST_CHANGE = "PHARMACIST_REVIEW_REQUEST_CHANGE"
    ORDER_DISPENSED = "ORDER_DISPENSED"
    ORDER_SHIPPED = "ORDER_SHIPPED"
    ORDER_DELIVERED = "ORDER_DELIVERED"
    ORDER_REFUNDED = "ORDER_REFUNDED"
    COLD_CHAIN_DISPOSED = "COLD_CHAIN_DISPOSED"
    ADR_SUBMITTED = "ADR_SUBMITTED"
    ADR_ARCHIVED = "ADR_ARCHIVED"
    VENDOR_SUSPENDED = "VENDOR_SUSPENDED"


class SubjectType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    ORDER = "ORDER"
    PHARMACIST_REVIEW = "PHARMACIST_REVIEW"
    COLD_CHAIN_SHIPMENT = "COLD_CHAIN_SHIPMENT"
    ADVERSE_REACTION_REPORT = "ADVERSE_REACTION_REPORT"
    VENDOR = "VENDOR"


class ExternalChannel(str, Enum):
    REGULATORY_AUTHORITY = "REGULATORY_AUTHORITY"
    PAYMENT = "PAYMENT"
    LOGISTICS = "LOGISTICS"
    E_PRESCRIPTION_PLATFORM = "E_PRESCRIPTION_PLATFORM"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true → id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class PharmaPlatform(TypedDict, total=False):
    id: str
    name: str
    jurisdiction: str
    current_clock_iso: str
    regulatory_endpoint: str
    created_at: str
    updated_at: str
    version: int


class Drug(TypedDict, total=False):
    id: str
    platform_id: str
    ndc: str
    name: str
    classification: str
    control_category: str
    cold_chain_required: bool
    indications: List[str]
    contraindications: List[str]
    per_order_qty_cap: int
    per_period_qty_cap: int
    vendor_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    platform_id: str
    name: str
    business_license_no: str
    business_license_expires_at: str
    drug_operation_permit_no: str
    drug_operation_permit_expires_at: str
    qualification_status: str
    latest_review_submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pharmacist(TypedDict, total=False):
    id: str
    platform_id: str
    full_name: str
    certificate_no: str
    certificate_expires_at: str
    qualification_status: str
    courier_qualified: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    platform_id: str
    real_name: str
    id_document_no: str
    special_population_flags: List[str]
    real_name_verified: bool
    created_at: str
    updated_at: str
    version: int


class PrescriptionDrugItem(TypedDict, total=False):
    drug_id: str
    qty: int


class Prescription(TypedDict, total=False):
    id: str
    platform_id: str
    customer_id: str
    prescriber_name: str
    prescriber_license_no: str
    image_url: str
    issued_at: str
    validity_days: int
    drug_items: List[PrescriptionDrugItem]
    reviewer_pharmacist_id: Optional[str]
    archived_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseLimitRule(TypedDict, total=False):
    id: str
    platform_id: str
    control_category: str
    window_days: int
    max_units_per_window: int
    blocks_special_populations: List[str]
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict, total=False):
    drug_id: str
    qty: int
    unit_price_cents: int


class Order(TypedDict, total=False):
    id: str
    platform_id: str
    customer_id: str
    prescription_id: Optional[str]
    items: List[OrderItem]
    total_amount_cents: int
    cold_chain_required: bool
    payment_status: str
    dispensing_status: str
    paid_at: Optional[str]
    pharmacist_review_id: Optional[str]
    cold_chain_shipment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PharmacistReview(TypedDict, total=False):
    id: str
    platform_id: str
    order_id: str
    assigned_pharmacist_id: str
    interaction_check_passed: Optional[bool]
    dosage_rationality_passed: Optional[bool]
    decision_notes: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict, total=False):
    recorded_at: str
    celsius_tenths: int


class ColdChainShipment(TypedDict, total=False):
    id: str
    platform_id: str
    order_id: str
    courier_pharmacist_id: str
    device_id: str
    dispatched_at: str
    temperature_readings: List[TemperatureReading]
    excursion_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseReactionReport(TypedDict, total=False):
    id: str
    platform_id: str
    order_id: Optional[str]
    drug_id: str
    customer_id: str
    reporter_kind: str
    severity: str
    reported_at: str
    reporting_deadline_at: str
    submitted_to_authority_at: Optional[str]
    follow_up_due_at: Optional[str]
    archived_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- Append-only logs: only id + created_at (no updated_at, no version) ----

class AuditLog(TypedDict, total=False):
    id: str
    platform_id: str
    subject_type: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    occurred_at: str
    payload: Any
    created_at: str


class ExternalEvent(TypedDict, total=False):
    id: str
    platform_id: str
    channel: str
    event_type: str
    subject_type: str
    subject_id: str
    occurred_at: str
    payload: Any
    idempotency_key: str
    created_at: str


class PrescriberDenylistEntry(TypedDict, total=False):
    id: str
    platform_id: str
    prescriber_license_no: str
    reason: str
    created_at: str
