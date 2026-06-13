"""Domain types: entity TypedDicts, status enums, role enum (Septic & Well Service)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum types ──────────────────────────────

class AccountStanding(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SiteComplianceStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    COMPLIANT = "COMPLIANT"
    CONDITIONAL = "CONDITIONAL"
    NON_COMPLIANT = "NON_COMPLIANT"


class AssetType(str, Enum):
    SEPTIC_TANK = "SEPTIC_TANK"
    WELL = "WELL"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ServicePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class WorkType(str, Enum):
    PUMPING = "PUMPING"
    INSPECTION = "INSPECTION"
    EMERGENCY = "EMERGENCY"
    REPAIR = "REPAIR"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class RouteStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class InspectionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class PermitFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReminderType(str, Enum):
    PUMP_DUE = "PUMP_DUE"
    COMPLIANCE_OVERDUE = "COMPLIANCE_OVERDUE"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    FIELD_TECH = "FieldTech"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER = "Customer"


# ─── Entity TypedDicts ────────────────────────────────
# Entities with common_fields: true carry id + created_at + updated_at + version.

class Account(TypedDict):
    id: str
    name: str
    billing_email: str
    standing: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    shift_start_minute: int
    shift_end_minute: int
    certified_for_wells: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    account_id: str
    address: str
    county_code: str
    service_minutes: int
    compliance_status: str
    risk_score: int
    last_pumped_date: Optional[str]
    next_pump_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    site_id: str
    asset_type: str
    capacity_gallons: int
    install_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    site_id: str
    frequency_months: int
    estimated_gallons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    site_id: str
    route_id: Optional[str]
    technician_id: Optional[str]
    work_type: str
    scheduled_date: str
    window_start_minute: int
    estimated_gallons: Optional[int]
    measured_gallons: Optional[int]
    emergency_surcharge_applies: bool
    status: str
    billing_status: str
    estimated_cost_cents: int
    final_cost_cents: int
    invoice_total_cents: int
    window_end_minute: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    technician_id: str
    route_date: str
    status: str
    assigned_stop_count: int
    booked_minutes: int
    optimized_sequence: List[str]
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict):
    id: str
    work_order_id: str
    result: Optional[str]
    defect_count: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitFiling(TypedDict):
    id: str
    inspection_report_id: str
    site_id: str
    county_code: str
    status: str
    submission_count: int
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairLine(TypedDict):
    id: str
    work_order_id: str
    part_name: str
    quantity: int
    unit_price_cents: int
    tax_rate_bps: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event; carries ONLY id + created_at
# (no updated_at, no version).
class Reminder(TypedDict):
    id: str
    site_id: str
    reminder_type: str
    due_date: str
    status: str
    created_at: str
