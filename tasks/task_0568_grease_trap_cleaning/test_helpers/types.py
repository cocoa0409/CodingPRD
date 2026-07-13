"""Domain types: entity TypedDicts, status enums, role enum for the FOG Compliance Service API.

All ten primary resources carry the four common fields (id, created_at, updated_at, version)
per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─────────────────────────── Role enum ───────────────────────────
class UserRole(str, Enum):
    ADMIN = "Admin"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BILLING_CLERK = "BillingClerk"


# ─────────────────────────── Status enums ───────────────────────────
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SiteComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"


class EquipmentType(str, Enum):
    GREASE_TRAP = "GREASE_TRAP"
    HOOD = "HOOD"


class EquipmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class EquipmentServiceState(str, Enum):
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


class ServiceContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class BillingCycle(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class CertificationLevel(str, Enum):
    BASIC = "BASIC"
    NFPA96_CERTIFIED = "NFPA96_CERTIFIED"


class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceType(str, Enum):
    SCHEDULED = "SCHEDULED"
    EMERGENCY = "EMERGENCY"


class WorkOrderPriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class ManifestComplianceFlag(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class ManifestStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class CleanlinessGrade(str, Enum):
    BARE_METAL_CLEAN = "BARE_METAL_CLEAN"
    ACCEPTABLE = "ACCEPTABLE"
    FAILING = "FAILING"


class ComplianceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# ─────────────────────────── Entity TypedDicts ───────────────────────────
class Customer(TypedDict):
    id: str
    business_name: str
    billing_email: str
    credit_limit_cents: int
    account_status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    customer_id: str
    address: str
    municipality_code: str
    permit_number: str
    compliance_status: str
    projected_compliance_status: str
    last_certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    site_id: str
    equipment_type: str
    capacity_gallons: float
    nominal_frequency_days: int
    status: str
    last_service_at: Optional[str]
    next_service_due_at: Optional[str]
    service_state: str
    lifetime_pumped_gallons: float
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    customer_id: str
    billing_cycle: str
    base_rate_cents: int
    tax_rate_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    certification_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    site_id: str
    equipment_id: str
    contract_id: Optional[str]
    technician_id: Optional[str]
    service_type: str
    priority: str
    planned_start: str
    planned_end: str
    status: str
    actual_hours: Optional[float]
    service_fee_cents: int
    emergency_surcharge_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PumpOutManifest(TypedDict):
    id: str
    work_order_id: str
    disposal_facility_name: str
    disposal_facility_permit: str
    hazmat_certified: bool
    volume_gallons: float
    fog_percentage: float
    manifest_number: str
    compliance_flag: str
    disposal_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HoodCertificate(TypedDict):
    id: str
    work_order_id: str
    cleanliness_grade: str
    sticker_number: str
    issued_at: str
    valid_until: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    site_id: str
    municipality_code: str
    period_start: str
    period_end: str
    status: str
    pumped_gallons_total: float
    included_manifest_count: int
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    customer_id: str
    contract_id: Optional[str]
    period_start: str
    period_end: str
    status: str
    provisional_total_cents: int
    subtotal_cents: int
    tax_cents: int
    total_amount_cents: int
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int
