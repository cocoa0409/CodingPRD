"""Domain types: entity TypedDicts, status enums, role enum for the Dust Compliance API."""
from enum import Enum
from typing import Optional, TypedDict


class SitePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    CONDITIONAL = "CONDITIONAL"
    DEFICIENT = "DEFICIENT"
    STOP_WORK = "STOP_WORK"


class SampleClass(str, Enum):
    ST0 = "ST0"
    ST1 = "ST1"
    ST2 = "ST2"
    ST3 = "ST3"


class CollectorStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class DpTrend(str, Enum):
    STABLE = "STABLE"
    RISING = "RISING"
    ALARM_HIGH = "ALARM_HIGH"


class DHAStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class ProgramPosture(str, Enum):
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"
    OVERDUE = "OVERDUE"
    SKIPPED = "SKIPPED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InspectorKind(str, Enum):
    AHJ = "AHJ"
    INSURER = "INSURER"
    INTERNAL = "INTERNAL"


class FindingSeverity(str, Enum):
    OBSERVATION = "OBSERVATION"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    DISPUTED = "DISPUTED"
    WITHDRAWN = "WITHDRAWN"


class ProjectStatus(str, Enum):
    SCOPING = "SCOPING"
    ESTIMATED = "ESTIMATED"
    APPROVED = "APPROVED"
    IN_EXECUTION = "IN_EXECUTION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IncidentKind(str, Enum):
    FIRE = "FIRE"
    DEFLAGRATION = "DEFLAGRATION"
    EMBER_RELEASE = "EMBER_RELEASE"
    NEAR_MISS = "NEAR_MISS"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CATASTROPHIC = "CATASTROPHIC"


class RootCauseCode(str, Enum):
    HOUSEKEEPING = "HOUSEKEEPING"
    HOT_WORK = "HOT_WORK"
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"
    STATIC_DISCHARGE = "STATIC_DISCHARGE"
    UNKNOWN = "UNKNOWN"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CAPA_DEFINED = "CAPA_DEFINED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class CAPAStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    OVERDUE = "OVERDUE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_MANAGER = "ComplianceManager"
    COMPLIANCE_ENGINEER = "ComplianceEngineer"
    SAFETY_MANAGER = "SafetyManager"
    HOT_WORK_PERFORMER = "HotWorkPerformer"
    HOUSEKEEPING_AUDITOR = "HousekeepingAuditor"
    INSPECTOR_USER = "InspectorUser"
    INCIDENT_INVESTIGATOR = "IncidentInvestigator"


class Site(TypedDict, total=False):
    id: str
    name: str
    address: str
    ahj_authority: str
    insurer_id: str
    posture: str
    posture_score: float
    open_critical_findings: int
    open_overdue_housekeeping: int
    hot_work_in_progress: int
    last_dha_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DustSample(TypedDict, total=False):
    id: str
    site_id: str
    material_name: str
    kst_bar_m_per_s: float
    pmax_bar_g: float
    mie_mj: float
    sample_class: str
    combustible: bool
    lab_report_ref: str
    created_at: str
    updated_at: str
    version: int


class Collector(TypedDict, total=False):
    id: str
    site_id: str
    tag: str
    dust_sample_id: str
    design_airflow_acfm: int
    filter_area_ft2: float
    air_to_cloth_ratio: float
    internal_volume_m3: float
    pred_max_bar_g: float
    required_vent_area_m2: float
    installed_vent_area_m2: float
    vent_adequate: bool
    dp_current_inwc: float
    dp_trend: str
    filter_change_due: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DHA(TypedDict, total=False):
    id: str
    site_id: str
    title: str
    author_id: str
    approver_id: Optional[str]
    kst_class_highest: str
    risk_score: float
    review_due_at: Optional[str]
    overdue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class HousekeepingProgram(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    target_accumulation_g_per_m2: float
    frequency_hours: int
    last_audit_at: Optional[str]
    next_due_at: Optional[str]
    current_posture: str
    created_at: str
    updated_at: str
    version: int


# Functional syntax: "pass" is a Python keyword and cannot be a class-body field.
HousekeepingAudit = TypedDict(
    "HousekeepingAudit",
    {
        "id": str,
        "program_id": str,
        "auditor_id": str,
        "measured_accumulation_g_per_m2": float,
        "pass_threshold_g_per_m2": float,
        "pass": bool,
        "scheduled_for": str,
        "executed_at": Optional[str],
        "status": str,
        "created_at": str,
        "updated_at": str,
        "version": int,
    },
    total=False,
)


class HotWorkPermit(TypedDict, total=False):
    id: str
    site_id: str
    collector_id: Optional[str]
    work_description: str
    issuer_id: str
    performer_id: str
    valid_from: str
    valid_to: str
    fire_watch_minutes_after: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    site_id: str
    inspector_kind: str
    inspector_ref: str
    conducted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict, total=False):
    id: str
    inspection_id: str
    collector_id: Optional[str]
    severity: str
    description: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RetrofitProject(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    trigger_finding_id: str
    scope_budget_cents: int
    estimated_cost_cents: int
    contingency_cents: int
    total_projected_cents: int
    contingency_rounding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetrofitLineItem(TypedDict, total=False):
    id: str
    project_id: str
    description: str
    cost_cents: int
    risk_tier: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    site_id: str
    occurred_at: str
    collector_id: Optional[str]
    kind: str
    description: str
    severity: str
    root_cause_code: str
    investigation_lead_id: str
    capa_count: int
    capa_open_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CAPAAction(TypedDict, total=False):
    id: str
    incident_id: str
    description: str
    owner_id: str
    due_at: str
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
