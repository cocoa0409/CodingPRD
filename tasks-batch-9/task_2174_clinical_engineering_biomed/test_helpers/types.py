"""Domain types for the clinical-engineering service: entity TypedDicts, state enums, roles."""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    CE_MANAGER = "CEManager"
    BIOMED_TECH = "BiomedTech"
    SECURITY_OFFICER = "SecurityOfficer"
    DEPT_STEWARD = "DeptSteward"
    VENDOR_REP = "VendorRep"


# ─── State enums ───────────────────────────────────────────────────────────

class CePosture(str, Enum):
    NORMAL = "NORMAL"
    HEIGHTENED = "HEIGHTENED"
    LOCKDOWN = "LOCKDOWN"


class BudgetState(str, Enum):
    OPEN = "OPEN"
    WARNING = "WARNING"
    ON_HOLD = "ON_HOLD"


class OperationalState(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DOWN = "DOWN"
    ON_LOAN = "ON_LOAN"
    RETIRED = "RETIRED"


class SecurityState(str, Enum):
    UNASSESSED = "UNASSESSED"
    ASSESSED_OK = "ASSESSED_OK"
    VULNERABLE = "VULNERABLE"
    QUARANTINED = "QUARANTINED"
    REMEDIATED = "REMEDIATED"


class RiskClass(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PMTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class PMResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PASS_WITH_DEFECT = "PASS_WITH_DEFECT"


class WorkOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    IN_REPAIR = "IN_REPAIR"
    AWAITING_PARTS = "AWAITING_PARTS"
    REPAIR_COMPLETE = "REPAIR_COMPLETE"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReportedSeverity(str, Enum):
    PATIENT_HARM = "PATIENT_HARM"
    CLINICAL_IMPACT = "CLINICAL_IMPACT"
    ROUTINE = "ROUTINE"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ServiceMode(str, Enum):
    IN_HOUSE = "IN_HOUSE"
    VENDOR = "VENDOR"


class LoanerStatus(str, Enum):
    NONE = "NONE"
    COVERED = "COVERED"
    UNCOVERED = "UNCOVERED"


class LoanerAssignmentStatus(str, Enum):
    DEPLOYED = "DEPLOYED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class LoanerSource(str, Enum):
    POOL = "POOL"
    RENTAL = "RENTAL"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    MANDATORY_REMOVAL = "MANDATORY_REMOVAL"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class HazardClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class MatchBasis(str, Enum):
    MODEL_ONLY = "MODEL_ONLY"
    MODEL_AND_LOT = "MODEL_AND_LOT"


class Disposition(str, Enum):
    PENDING = "PENDING"
    REMOVED = "REMOVED"
    REMEDIATED = "REMEDIATED"
    EXEMPTED = "EXEMPTED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SCHEDULED = "REMEDIATION_SCHEDULED"
    MITIGATED = "MITIGATED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


class FindingResolution(str, Enum):
    MITIGATED = "MITIGATED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


# ─── Entity shapes (PRD §2.4: all twelve resources carry the full common set) ──

class Facility(TypedDict):
    id: str
    name: str
    facility_code: str
    pm_compliance_target_pct: float
    ce_posture: str
    pm_compliance_pct_strict: float
    pm_compliance_pct_operational: float
    pm_audit_index: int
    open_class_i_recall_count: int
    departments_on_hold_count: int
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    facility_id: str
    name: str
    cost_center_code: str
    downtime_budget_cents: int
    downtime_spend_cents: int
    budget_state: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_code: str
    hourly_rate_cents: int
    travel_flat_cents: int
    security_attestation_on_file: bool
    is_approved: bool
    created_at: str
    updated_at: str
    version: int


class DeviceModel(TypedDict):
    id: str
    manufacturer: str
    model_number: str
    device_family: str
    is_network_connected: bool
    expected_life_years: int
    replacement_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    facility_id: str
    department_id: str
    device_model_id: str
    serial_number: str
    lot_number: Optional[str]
    acquisition_date: str
    acquisition_cost_cents: int
    function_code: int
    physical_risk_code: int
    maintenance_requirement_code: int
    condition_score: int
    utilization_hours: int
    is_loaner_pool: bool
    risk_score: int
    risk_class: str
    pm_interval_days: int
    operational_state: str
    security_state: str
    recall_hold: bool
    lifetime_maintenance_cost_cents: int
    replacement_priority_score: float
    plan_rank: int
    plan_funded: bool
    created_at: str
    updated_at: str
    version: int


class PMTask(TypedDict):
    id: str
    device_id: str
    window_start: str
    window_end: str
    due_at: str
    original_due_at: str
    status: str
    deferral_count: int
    result: Optional[str]
    labor_minutes: int
    completed_at: Optional[str]
    completed_by_user_id: Optional[str]
    on_time: bool
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    device_id: str
    vendor_id: Optional[str]
    service_contract_id: Optional[str]
    origin_security_finding_id: Optional[str]
    reported_severity: str
    problem_summary: str
    reported_at: str
    status: str
    priority: str
    sla_hours: int
    service_mode: Optional[str]
    assigned_user_id: Optional[str]
    repaired_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    repair_started_at: Optional[str]
    repair_completed_at: Optional[str]
    closed_at: Optional[str]
    active_repair_seconds: int
    active_repair_hours: float
    turnaround_hours: float
    sla_met: bool
    labor_minutes: int
    parts_cost_cents: int
    shift_multiplier_applied: float
    estimated_cost_cents: int
    final_cost_cents: int
    department_charge_cents: int
    verify_fail_count: int
    loaner_status: str
    created_at: str
    updated_at: str
    version: int


class LoanerAssignment(TypedDict):
    id: str
    work_order_id: str
    loaner_device_id: Optional[str]
    source: str
    start_at: str
    end_at: str
    returned_at: Optional[str]
    status: str
    billable_days: int
    rental_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    facility_id: str
    device_model_id: str
    source_reference: str
    hazard_class: str
    affected_lot_numbers: List[str]
    response_due_at: str
    published_at: Optional[str]
    status: str
    matched_device_count: int
    pending_match_count: int
    created_at: str
    updated_at: str
    version: int


class RecallMatch(TypedDict):
    id: str
    recall_notice_id: str
    device_id: str
    match_basis: str
    disposition: str
    disposed_at: Optional[str]
    disposed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict):
    id: str
    vendor_id: str
    device_model_id: str
    coverage_start: str
    coverage_end: str
    annual_premium_cents: int
    deductible_cents: int
    covered_event_cap: int
    covered_events_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityFinding(TypedDict):
    id: str
    device_id: str
    severity: str
    advisory_reference: str
    requires_downtime: bool
    discovered_at: str
    remediation_due_at: str
    status: str
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
