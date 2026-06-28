"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full audit field set (id, created_at,
updated_at, version) per PRD §2.4 — there are no audit-light entities.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    DOCTOR = "Doctor"
    LAB_TECH = "LabTech"
    SCHEDULER = "Scheduler"
    BILLING = "Billing"
    LAB_ADMIN = "LabAdmin"


# ─── Status enums (PRD §3 narratives) ─────────────────────────────────
class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    DESIGN = "DESIGN"
    FABRICATION = "FABRICATION"
    TRY_IN = "TRY_IN"
    REVISION = "REVISION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FabricationUnitStatus(str, Enum):
    QUEUED = "QUEUED"
    MILLING = "MILLING"
    MILLED = "MILLED"
    TRIED_IN = "TRIED_IN"
    PASSED = "PASSED"
    REMADE_OUT = "REMADE_OUT"


class MillJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class MillMachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvoiceKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceBillingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceDeliveryStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class CreditMemoStatus(str, Enum):
    ISSUED = "ISSUED"
    VOID = "VOID"


class RemakeRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    COMPLETED = "COMPLETED"


# ─── Domain enums for input fields ────────────────────────────────────
class IntakeMethod(str, Enum):
    RX_PAPER = "RX_PAPER"
    IMPRESSION = "IMPRESSION"
    INTRAORAL_SCAN = "INTRAORAL_SCAN"


class RestorationType(str, Enum):
    CROWN = "CROWN"
    BRIDGE = "BRIDGE"
    DENTURE = "DENTURE"
    ALIGNER = "ALIGNER"


class FabricationProcess(str, Enum):
    MILLED = "MILLED"
    PRINTED = "PRINTED"


class RemakeReason(str, Enum):
    SHADE_MISMATCH = "SHADE_MISMATCH"
    POOR_FIT = "POOR_FIT"
    FRACTURE = "FRACTURE"
    CONTACT_OPEN = "CONTACT_OPEN"


# ─── Entity TypedDicts (all carry full audit fields per PRD §2.4) ─────
class Doctor(TypedDict):
    id: str
    full_name: str
    practice_name: str
    email: str
    completed_case_count: int
    account_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Material(TypedDict):
    id: str
    code: str
    name: str
    base_unit_price_cents: int
    fabrication_process: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class MillMachine(TypedDict):
    id: str
    name: str
    capability: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourierRoute(TypedDict):
    id: str
    label: str
    service_date: str
    max_stops: int
    buffer_minutes: int
    stop_count: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    doctor_id: str
    intake_method: str
    is_rush: bool
    status: str
    scheduled_start_at: Optional[str]
    promised_ready_at: Optional[str]
    shipped_at: Optional[str]
    sla_breached: bool
    revision_count: int
    billable_unit_count: int
    created_at: str
    updated_at: str
    version: int


class Restoration(TypedDict):
    id: str
    case_id: str
    material_id: str
    restoration_type: str
    unit_count: int
    requested_shade: str
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class FabricationUnit(TypedDict):
    id: str
    restoration_id: str
    remade_from_unit_id: Optional[str]
    status: str
    is_billable: bool
    created_at: str
    updated_at: str
    version: int


class ShadeRecord(TypedDict):
    id: str
    restoration_id: str
    shade_code: str
    matched: bool
    created_at: str
    updated_at: str
    version: int


class MillJob(TypedDict):
    id: str
    fabrication_unit_id: str
    mill_machine_id: str
    start_at: str
    duration_minutes: int
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    courier_route_id: str
    case_id: str
    window_start_at: str
    window_minutes: int
    window_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    case_id: str
    kind: str
    subtotal_cents: int
    rush_surcharge_cents: int
    discount_cents: int
    tax_cents: int
    sla_credit_cents: int
    total_cents: int
    billing_status: str
    delivery_status: str
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict):
    id: str
    case_id: str
    invoice_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RemakeRequest(TypedDict):
    id: str
    case_id: str
    fabrication_unit_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
