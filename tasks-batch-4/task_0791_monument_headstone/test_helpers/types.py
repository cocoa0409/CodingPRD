"""Domain types: entity TypedDicts, status enums, role enum.

All names use Monument & Headstone Service PRD terminology.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    ADMIN = "Admin"
    CUSTOMER = "Customer"
    DESIGNER = "Designer"
    SHOP_MANAGER = "ShopManager"
    FIELD_OPS = "FieldOps"


# --- MonumentOrder parallel axes (PRD §3) ---
class ProductionStatus(str, Enum):
    DRAFTING = "DRAFTING"
    IN_FABRICATION = "IN_FABRICATION"
    READY_TO_INSTALL = "READY_TO_INSTALL"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class DesignProofStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class PaymentType(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class PaymentCaptureStatus(str, Enum):
    CAPTURED = "CAPTURED"


class FabricationJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CemeteryPermitStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class InstallationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RestorationJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSESSED = "ASSESSED"
    CANCELLED = "CANCELLED"


# --- Value enums ---
class SubjectType(str, Enum):
    HUMAN = "HUMAN"
    PET = "PET"


class Material(str, Enum):
    GRANITE = "GRANITE"
    BRONZE = "BRONZE"
    MARBLE = "MARBLE"


class ServiceType(str, Enum):
    CLEANING = "CLEANING"
    REPAIR = "REPAIR"
    REFINISH = "REFINISH"


class Condition(str, Enum):
    NORMAL = "NORMAL"
    SEVERE = "SEVERE"


# --- Entity TypedDicts ---
# Entities carrying common fields (id, created_at, updated_at, version).

class Cemetery(TypedDict, total=False):
    id: str
    name: str
    allowed_materials: List[str]
    max_height_cm: int
    max_width_cm: int
    max_base_width_cm: int
    requires_permit: bool
    permit_fee_cents: int
    requires_foundation: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonumentOrder(TypedDict, total=False):
    id: str
    customer_id: str
    cemetery_id: str
    subject_type: str
    material: str
    height_cm: int
    width_cm: int
    base_width_cm: int
    estimated_line_char_counts: List[int]
    production_status: str
    payment_status: str
    current_proof_id: Optional[str]
    provisional_merchandise_cents: int
    merchandise_price_cents: int
    contract_total_cents: int
    deposit_amount_cents: int
    balance_amount_cents: int
    amount_paid_cents: int
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DesignProof(TypedDict, total=False):
    id: str
    order_id: str
    engraving_text: str
    line_char_counts: List[int]
    layout_spec: Optional[str]
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Workshop(TypedDict, total=False):
    id: str
    name: str
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class FabricationJob(TypedDict, total=False):
    id: str
    order_id: str
    workshop_id: str
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CemeteryPermit(TypedDict, total=False):
    id: str
    order_id: str
    cemetery_id: str
    permit_number: str
    placement_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallationCrew(TypedDict, total=False):
    id: str
    name: str
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class Installation(TypedDict, total=False):
    id: str
    order_id: str
    crew_id: str
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestorationJob(TypedDict, total=False):
    id: str
    order_id: str
    workshop_id: Optional[str]
    service_type: str
    is_warranty: bool
    reported_area_cm2: int
    measured_area_cm2: Optional[int]
    condition: Optional[str]
    quoted_cost_cents: int
    assessed_cost_cents: Optional[int]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    duration_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — Payment is immutable, carries ONLY id + created_at (PRD §2.4).
class Payment(TypedDict, total=False):
    id: str
    order_id: str
    payment_type: str
    amount_cents: int
    signed_amount_cents: int
    status: str
    created_at: str
