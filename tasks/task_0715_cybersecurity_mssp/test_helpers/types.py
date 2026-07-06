"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum members match the PRD contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class ClientPosture(str, Enum):
    OPEN = "OPEN"
    HEIGHTENED = "HEIGHTENED"
    LOCKDOWN = "LOCKDOWN"


class RetainerLedgerStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EngagementKind(str, Enum):
    VULN_SCAN = "VULN_SCAN"
    PENTEST = "PENTEST"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    DECOMMISSIONED = "DECOMMISSIONED"


class AssetCriticality(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CROWN_JEWEL = "CROWN_JEWEL"


class AssetExposure(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class ScanStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class FindingSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_IN_PROGRESS = "REMEDIATION_IN_PROGRESS"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    RETEST_FAILED = "RETEST_FAILED"
    REMEDIATED = "REMEDIATED"
    RISK_ACCEPTED = "RISK_ACCEPTED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class AlertSource(str, Enum):
    SIEM = "SIEM"
    EDR = "EDR"


class AlertTriagePriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class AlertStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    DISMISSED = "DISMISSED"
    PROMOTED = "PROMOTED"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONTAINED = "CONTAINED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class AuditFramework(str, Enum):
    SOC2 = "SOC2"
    HIPAA = "HIPAA"
    PCI = "PCI"


class ComplianceAuditStatus(str, Enum):
    PLANNING = "PLANNING"
    FIELDWORK = "FIELDWORK"
    READY = "READY"
    ATTESTED = "ATTESTED"
    FAILED = "FAILED"


class AuditEvidenceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReportKind(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    INCIDENT = "INCIDENT"
    COMPLIANCE = "COMPLIANCE"
    RETAINER = "RETAINER"


class ReportStatus(str, Enum):
    GENERATED = "GENERATED"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ENGAGEMENT_LEAD = "EngagementLead"
    SOC_ANALYST = "SocAnalyst"
    AUDITOR = "Auditor"
    CLIENT_CONTACT = "ClientContact"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities carrying id + created_at + updated_at + version.

class Client(TypedDict):
    id: str
    name: str
    tier: str
    retainer_hours_per_period: float
    current_period_index: int
    posture: str
    open_critical_findings: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetainerLedger(TypedDict):
    id: str
    client_id: str
    period_index: int
    hours_granted: float
    hours_reserved: float
    hours_consumed: float
    hours_available: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    client_id: str
    kind: str
    authorized_window_start: str
    authorized_window_end: str
    estimated_hours: float
    scope_asset_ids: List[str]
    authorization_signed_by: Optional[str]
    period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    client_id: str
    hostname: str
    ip_address: str
    criticality: str
    exposure: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Scan(TypedDict):
    id: str
    engagement_id: str
    client_id: str
    started_at: Optional[str]
    completed_at: Optional[str]
    actual_hours: Optional[float]
    raw_finding_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict):
    id: str
    scan_id: str
    asset_id: str
    client_id: str
    title: str
    cvss_base: float
    severity: str
    sla_due_at: Optional[str]
    sla_breached: bool
    submitted_by: Optional[str]
    accepted_by: Optional[str]
    linked_incident_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict):
    id: str
    client_id: str
    asset_id: str
    source: str
    raw_score: float
    triage_priority: str
    triaged_by: Optional[str]
    promoted_incident_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    client_id: str
    triggering_alert_id: Optional[str]
    severity: str
    response_hours: float
    escalation_deadline_at: Optional[str]
    escalation_breached: bool
    contained_count: int
    resolved_period_index: Optional[int]
    quarantined_asset_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict):
    id: str
    client_id: str
    framework: str
    required_control_count: int
    readiness_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEvidence(TypedDict):
    id: str
    audit_id: str
    control_ref: str
    finding_id: Optional[str]
    submitted_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    client_id: str
    kind: str
    subject_id: Optional[str]
    snapshot: dict
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only log entry: carries ONLY id + created_at (no updated_at, no version).
class AuditLogEntry(TypedDict):
    id: str
    client_id: str
    actor_role: str
    actor_user_id: str
    action: str
    target_entity: str
    target_id: str
    prev_hash: str
    entry_hash: str
    created_at: str
