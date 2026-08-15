"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity narratives (section 3) and common-resource
guarantees (section 2.4).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD section 3)
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ContractorStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LeadStatus(str, Enum):
    NEW = "NEW"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    INSPECTING = "INSPECTING"
    REMEDIATION = "REMEDIATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class InspectionOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    RECONCILED = "RECONCILED"
    VOID = "VOID"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


class TrcFlag(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class Sector(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"


class MeasureType(str, Enum):
    HVAC = "HVAC"
    INSULATION = "INSULATION"
    LIGHTING = "LIGHTING"
    WATER_HEATING = "WATER_HEATING"
    SOLAR = "SOLAR"


class SourceChannel(str, Enum):
    WEB = "WEB"
    CALL_CENTER = "CALL_CENTER"
    FIELD_AUDIT = "FIELD_AUDIT"
    REFERRAL = "REFERRAL"
    UTILITY_REFERRAL = "UTILITY_REFERRAL"


class PayeeRole(str, Enum):
    CONTRACTOR = "CONTRACTOR"
    CUSTOMER = "CUSTOMER"


class ComplaintCategory(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    SCHEDULING = "SCHEDULING"
    BILLING = "BILLING"
    CONDUCT = "CONDUCT"
    OTHER = "OTHER"


class ComplaintSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    CONTRACTOR = "Contractor"
    INSPECTOR = "Inspector"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every resource carries id, created_at, updated_at,
# version (PRD section 2.4).
# ---------------------------------------------------------------------------

class Program(TypedDict, total=False):
    id: str
    code: str
    name: str
    sector: str
    budget_cents: int
    committed_cents: int
    paid_cents: int
    avoided_kwh_target: int
    avoided_kwh_actual: int
    trc_threshold: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    legal_name: str
    license_number: str
    sector: str
    service_zip_codes: List[str]
    qa_score_bps: int
    qa_window_size: int
    active_certification_count: int
    on_time_installs: int
    late_installs: int
    complaint_count_90d: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    contractor_id: str
    measure_type: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    service_zip: str
    sector: str
    utility_account_id: str
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict, total=False):
    id: str
    customer_id: str
    program_id: str
    measure_type: str
    estimated_annual_kwh_savings: int
    source_channel: str
    assigned_contractor_id: Optional[str]
    distribution_decision: Optional[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    lead_id: str
    customer_id: str
    contractor_id: str
    program_id: str
    measure_type: str
    measure_cost_cents: int
    estimated_annual_kwh_savings: int
    incentive_recipient: str
    incentive_amount_cents: int
    incentive_amount_provisional_cents: int
    approval_snapshot_contractor_qa_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    project_id: str
    contractor_id: str
    scheduled_on: str
    duration_hours: int
    direct_install: bool
    assigned_inspector_id: Optional[str]
    completed_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    excluded_contractor_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    work_order_id: str
    project_id: str
    inspector_id: str
    scheduled_on: str
    outcome: str
    score_bps: int
    failure_reasons: List[str]
    remediation_required_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncentivePayment(TypedDict, total=False):
    id: str
    project_id: str
    payee_role: str
    payee_id: str
    amount_cents: int
    amount_provisional_cents: int
    reconciliation_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    customer_id: str
    contractor_id: str
    project_id: Optional[str]
    category: str
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CostEffectivenessReport(TypedDict, total=False):
    id: str
    program_id: str
    period_start: str
    period_end: str
    total_incentive_paid_cents: int
    total_admin_cost_cents: int
    total_avoided_kwh: int
    trc_ratio: float
    trc_flag: str
    status: str
    created_at: str
    updated_at: str
    version: int
