"""Domain types for the Appliance Repair & Extended-Warranty Service API.

Entity TypedDicts, status/enum classes, and the role enum. Every entity in this
system carries the common system-managed fields id, created_at, updated_at, and
version (PRD §2.4), so each TypedDict lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enums ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    TECHNICIAN = "Technician"
    DISPATCHER = "Dispatcher"
    SERVICE_ADMIN = "ServiceAdmin"


class RecallStatusValue(str, Enum):
    CLEAR = "CLEAR"
    RECALLED = "RECALLED"


class CoverageType(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    EXTENDED = "EXTENDED"
    HOME_WARRANTY = "HOME_WARRANTY"


class WarrantyRouting(str, Enum):
    NONE = "NONE"
    MANUFACTURER = "MANUFACTURER"
    EXTENDED = "EXTENDED"
    HOME_WARRANTY = "HOME_WARRANTY"


class TechnicianStatus(str, Enum):
    ON_DUTY = "ON_DUTY"
    OFF_DUTY = "OFF_DUTY"


class ServiceRequestStatus(str, Enum):
    INTAKE = "INTAKE"
    SCHEDULED = "SCHEDULED"
    DIAGNOSED = "DIAGNOSED"
    APPROVED = "APPROVED"
    AWAITING_PARTS = "AWAITING_PARTS"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    SAFETY_HOLD = "SAFETY_HOLD"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EstimateStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class PartsOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    BACKORDERED = "BACKORDERED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    RECORDED = "RECORDED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    CASH = "CASH"


class RecallNoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    address: str
    created_at: str
    updated_at: str
    version: int


class Appliance(TypedDict):
    id: str
    customer_id: str
    brand: str
    model: str
    serial_number: str
    purchase_date: str
    recall_status: str
    completed_repair_count: int
    health_score: int
    created_at: str
    updated_at: str
    version: int


class WarrantyContract(TypedDict):
    id: str
    appliance_id: str
    coverage_type: str
    coverage_start: str
    coverage_end: str
    deductible_cents: int
    coverage_cap_cents: int
    claimed_cents: int
    remaining_coverage_cents: int
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    part_number: str
    name: str
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TruckStockItem(TypedDict):
    id: str
    technician_id: str
    part_id: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int
    created_at: str
    updated_at: str
    version: int


class ServiceZone(TypedDict):
    id: str
    name: str
    max_concurrent_appointments: int
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    customer_id: str
    appliance_id: str
    assigned_technician_id: Optional[str]
    covering_contract_id: Optional[str]
    reported_issue: str
    status: str
    warranty_routing: str
    diagnostic_fee_cents: int
    health_score_at_diagnosis: int
    final_parts_total_cents: int
    final_labor_total_cents: int
    final_repair_subtotal_cents: int
    warranty_covered_cents: int
    customer_responsibility_cents: int
    amount_due_cents: int
    visit_count: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    service_request_id: str
    technician_id: str
    zone_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    service_request_id: str
    labor_tasks: List[dict]
    required_parts: List[dict]
    estimated_parts_total_cents: int
    estimated_labor_total_cents: int
    estimated_repair_subtotal_cents: int
    estimated_diagnostic_fee_cents: int
    estimated_total_cents: int
    estimated_customer_responsibility_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsOrder(TypedDict):
    id: str
    service_request_id: str
    part_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    service_request_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    brand: str
    model: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int
