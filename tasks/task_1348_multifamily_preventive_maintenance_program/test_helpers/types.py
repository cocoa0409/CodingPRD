"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    TECHNICIAN = "Technician"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class OccupancyStatus(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"


class ComponentType(str, Enum):
    HVAC = "HVAC"
    WATER_HEATER = "WATER_HEATER"
    APPLIANCE = "APPLIANCE"


class OperationalStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    NON_COMPLIANT = "NON_COMPLIANT"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    CLOSED = "CLOSED"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTIFIED = "NOTIFIED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_ACCESS = "NO_ACCESS"
    CANCELLED = "CANCELLED"


class EvidenceType(str, Enum):
    FILTER_REPLACEMENT = "FILTER_REPLACEMENT"
    DETECTOR_TEST = "DETECTOR_TEST"
    BATTERY_REPLACEMENT = "BATTERY_REPLACEMENT"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"


class DeficiencyStatus(str, Enum):
    RECORDED = "RECORDED"
    TRIAGED = "TRIAGED"
    CONVERTED = "CONVERTED"
    WAIVED = "WAIVED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AuditOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ForecastVariant(str, Enum):
    AGE_BASED = "AGE_BASED"
    CONDITION_BASED = "CONDITION_BASED"


class LedgerEntryKind(str, Enum):
    VISIT_COMMIT = "VISIT_COMMIT"
    VISIT_SETTLE = "VISIT_SETTLE"
    VISIT_RELEASE = "VISIT_RELEASE"
    WO_COMMIT = "WO_COMMIT"
    WO_SETTLE = "WO_SETTLE"
    WO_RELEASE = "WO_RELEASE"


# --- Entities carrying the standard system-managed fields (id, created_at,
# updated_at, version) ---


class Property(TypedDict, total=False):
    id: str
    property_code: str
    display_name: str
    notice_lead_hours: int
    default_labor_rate_cents_per_hour: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict, total=False):
    id: str
    property_id: str
    building_label: str
    floors: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    building_id: str
    unit_number: str
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    unit_id: str
    component_type: str
    installed_on: str
    warranty_months: int
    expected_life_months: int
    replacement_cost_cents: int
    condition_score: Optional[int]
    age_months: int
    warranty_active: bool
    operational_status: str
    compliance_status: str
    superseded_by_asset_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PMTaskTemplate(TypedDict, total=False):
    id: str
    property_id: str
    component_type: str
    task_name: str
    frequency_days: int
    estimated_labor_minutes: int
    requires_evidence: bool
    effective_from: str
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PMPlan(TypedDict, total=False):
    id: str
    property_id: str
    plan_year: int
    budget_cents: int
    planned_labor_hours: int
    actual_labor_minutes: int
    committed_cents: int
    spent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EntryBatch(TypedDict, total=False):
    id: str
    property_id: str
    batch_label: str
    window_start: str
    window_end: str
    status: str
    notice_sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PMVisit(TypedDict, total=False):
    id: str
    batch_id: str
    unit_id: str
    template_id: str
    asset_id: str
    plan_id: str
    scheduled_start: str
    technician_id: str
    actual_minutes: Optional[int]
    condition_score_recorded: Optional[int]
    visit_status: str
    visit_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict, total=False):
    id: str
    visit_id: str
    asset_id: str
    severity: str
    description: str
    status: str
    work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveWorkOrder(TypedDict, total=False):
    id: str
    property_id: str
    deficiency_id: str
    plan_id: str
    asset_id: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    assigned_technician_id: str
    replace_asset: bool
    status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


# --- Append-only record types: only id + created_at, no updated_at/version ---


class ComplianceEvidence(TypedDict, total=False):
    id: str
    visit_id: str
    evidence_type: str
    serial_or_lot: str
    notes: str
    recorded_by: str
    created_at: str


class BudgetLedgerEntry(TypedDict, total=False):
    id: str
    plan_id: str
    entry_kind: str
    amount_cents: int
    source_visit_id: Optional[str]
    source_work_order_id: Optional[str]
    memo: str
    created_at: str


class CapitalForecastSnapshot(TypedDict, total=False):
    id: str
    property_id: str
    horizon_years: int
    variant: str
    total_projected_cents: int
    per_year_cents: List[int]
    asset_count_projected: int
    computed_at: str
    created_at: str


class CompletionAudit(TypedDict, total=False):
    id: str
    visit_id: str
    auditor_id: str
    outcome: str
    fail_reason: Optional[str]
    audited_at: str
    created_at: str
