"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    EHSAdministrator = "EHSAdministrator"
    Manager = "Manager"
    Employee = "Employee"
    VendingTechnician = "VendingTechnician"
    SafetyOfficer = "SafetyOfficer"
    FinanceAnalyst = "FinanceAnalyst"
    ComplianceAuditor = "ComplianceAuditor"
    Any = "Any"


class ItemCategory(str, Enum):
    GENERAL = "GENERAL"
    RESPIRATOR = "RESPIRATOR"
    FALL_PROTECTION = "FALL_PROTECTION"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MachineStatus(str, Enum):
    COMMISSIONING = "COMMISSIONING"
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"
    IN_SERVICE = "IN_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class SerializedUnitStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ISSUED = "ISSUED"
    INSPECTION_DUE = "INSPECTION_DUE"
    QUARANTINED = "QUARANTINED"


class ManagerOverrideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class IssuanceStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class RestockOrderStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    PICKED = "PICKED"
    LOADED = "LOADED"
    CANCELLED = "CANCELLED"


class RestockOrderSource(str, Enum):
    AUTO_PAR = "AUTO_PAR"
    MANUAL = "MANUAL"


class ServiceTicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


class IssueCode(str, Enum):
    JAM = "JAM"
    DOOR_FAULT = "DOOR_FAULT"
    NETWORK = "NETWORK"
    DISPLAY = "DISPLAY"
    PLANOGRAM_CHANGE = "PLANOGRAM_CHANGE"
    PREVENTIVE = "PREVENTIVE"


class ChargebackBatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class AuditScope(str, Enum):
    OVERRIDE_USAGE = "OVERRIDE_USAGE"
    INSPECTION_COMPLIANCE = "INSPECTION_COMPLIANCE"


class AuditStatus(str, Enum):
    DRAFT = "DRAFT"
    FIELDWORK = "FIELDWORK"
    FINDINGS_FILED = "FINDINGS_FILED"
    CLOSED = "CLOSED"


class ReasonCode(str, Enum):
    MEDICAL = "MEDICAL"
    NEW_HIRE = "NEW_HIRE"
    INCIDENT = "INCIDENT"
    PROJECT = "PROJECT"
    OTHER = "OTHER"


class FitTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FitTestStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# All entities carry common_fields: id + created_at + updated_at + version.
# ---------------------------------------------------------------------------


class CostCenter(TypedDict, total=False):
    id: str
    cost_center_code: str
    name: str
    ytd_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class JobRole(TypedDict, total=False):
    id: str
    role_name: str
    description: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    requires_fit_test: bool
    serialized_tracking: bool
    inspection_interval_days: Optional[int]
    base_list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractPrice(TypedDict, total=False):
    id: str
    item_id: str
    min_period_qty: int
    unit_price_cents: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    job_role_id: str
    home_cost_center_id: str
    is_manager: bool
    fit_tests: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class VendingMachine(TypedDict, total=False):
    id: str
    location_code: str
    site_name: str
    model: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineSlot(TypedDict, total=False):
    id: str
    machine_id: str
    slot_code: str
    item_id: str
    capacity: int
    par_level: int
    on_hand_qty: int
    created_at: str
    updated_at: str
    version: int


class SerializedUnit(TypedDict, total=False):
    id: str
    item_id: str
    serial_number: str
    slot_id: str
    issued_to_employee_id: Optional[str]
    last_inspected_on: Optional[str]
    next_inspection_due_on: Optional[str]
    inspection_log: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class ManagerOverride(TypedDict, total=False):
    id: str
    employee_id: str
    item_id: str
    approved_qty: int
    consumed_qty: int
    remaining_qty: int
    valid_from: str
    valid_until: str
    reason_code: str
    granted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IssuanceTransaction(TypedDict, total=False):
    id: str
    employee_id: str
    machine_id: str
    slot_id: str
    item_id: str
    serialized_unit_id: Optional[str]
    qty: int
    unit_price_cents: int
    line_total_cents: int
    cost_center_id: str
    manager_override_id: Optional[str]
    override_drawn_qty: int
    idempotency_key: str
    vended_at: str
    chargeback_batch_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RestockOrder(TypedDict, total=False):
    id: str
    machine_id: str
    slot_id: str
    item_id: str
    qty: int
    suggested_qty: int
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict, total=False):
    id: str
    machine_id: str
    issue_code: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargebackBatch(TypedDict, total=False):
    id: str
    cost_center_id: str
    period_start: str
    period_end: str
    line_count: int
    snapshot_total_cents: int
    rerated_total_cents: int
    adjustment_cents: int
    admin_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    scope: str
    period_start: str
    period_end: str
    exceptions_count: int
    findings_detail: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int
