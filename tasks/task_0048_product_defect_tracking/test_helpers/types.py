"""Domain types: entity TypedDicts, status enums, role enum.

Status enums mirror the discrete values listed in PRD §3 prose and §1 entity
definitions. Entities with common fields (id, created_at, updated_at, version)
are distinguished from append-only logs (id + created_at only), as called out
in PRD §2.4.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enumeration (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    """The five role names recognised in PRD §2.1, spelled exactly."""
    TRIAGE_MANAGER = "TriageManager"
    DEVELOPER = "Developer"
    QA_ENGINEER = "QAEngineer"
    RELEASE_MANAGER = "ReleaseManager"
    ANY = "Any"


# ---------------------------------------------------------------------------
# TeamMember persisted role (distinct from X-User-Role).
# PRD §3.1: "role enum value drawn from DEVELOPER, QA_ENGINEER,
# TRIAGE_MANAGER, or RELEASE_MANAGER".
# ---------------------------------------------------------------------------
class TeamMemberRole(str, Enum):
    DEVELOPER = "DEVELOPER"
    QA_ENGINEER = "QA_ENGINEER"
    TRIAGE_MANAGER = "TRIAGE_MANAGER"
    RELEASE_MANAGER = "RELEASE_MANAGER"


class TeamMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ---------------------------------------------------------------------------
# Project / Module
# ---------------------------------------------------------------------------
class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ModuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# Defect
# ---------------------------------------------------------------------------
class DefectStatus(str, Enum):
    """PRD §1.1 / §3 prose: NEW | ASSIGNED | IN_PROGRESS | FIXED |
    VERIFIED | REOPENED | CLOSED."""
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    FIXED = "FIXED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class DefectSlaState(str, Enum):
    """PRD §3.8: 'sla_state' dimension runs parallel to status."""
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class DefectSeverity(str, Enum):
    BLOCKER = "BLOCKER"
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    TRIVIAL = "TRIVIAL"


class DefectSource(str, Enum):
    INTERNAL_TEST = "INTERNAL_TEST"
    USER_FEEDBACK = "USER_FEEDBACK"
    ONLINE_MONITORING = "ONLINE_MONITORING"


class BusinessImpact(str, Enum):
    REVENUE_BLOCKING = "REVENUE_BLOCKING"
    CUSTOMER_FACING = "CUSTOMER_FACING"
    INTERNAL = "INTERNAL"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Severity Override
# ---------------------------------------------------------------------------
class SeverityOverrideStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Regression Run
# ---------------------------------------------------------------------------
class RegressionRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class RegressionRunResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# SLA Pause / Verification / External event sync
# ---------------------------------------------------------------------------
class SlaPauseReason(str, Enum):
    WAITING_ON_REPORTER = "WAITING_ON_REPORTER"
    WAITING_ON_THIRD_PARTY = "WAITING_ON_THIRD_PARTY"


class VerificationOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class AttachmentType(str, Enum):
    SCREENSHOT = "SCREENSHOT"
    LOG = "LOG"
    VIDEO = "VIDEO"


class AuditEventType(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    SEVERITY_CHANGE = "SEVERITY_CHANGE"
    ASSIGNMENT_CHANGE = "ASSIGNMENT_CHANGE"
    SLA_PAUSE = "SLA_PAUSE"
    SLA_RESUME = "SLA_RESUME"
    ESCALATION = "ESCALATION"
    EXTERNAL_EVENT_SYNC = "EXTERNAL_EVENT_SYNC"


class ExternalEventSystem(str, Enum):
    """PRD §3.12: 'a system value drawn from VCS, CI_CD, or IM'."""
    VCS = "VCS"
    CI_CD = "CI_CD"
    IM = "IM"


class GroupByDimension(str, Enum):
    MODULE = "module"
    SEVERITY = "severity"
    ASSIGNEE = "assignee"
    PERIOD = "period"


class DensityMode(str, Enum):
    PROVISIONAL = "provisional"
    FINAL = "final"


# ---------------------------------------------------------------------------
# Entity TypedDicts. common_fields branching is observed strictly: append-only
# rows (DefectAttachment, DuplicateLink, FixRecord, VerificationRecord,
# SLAPause, AuditEntry) carry only id + created_at — never updated_at /
# version.
# ---------------------------------------------------------------------------
class Project(TypedDict):
    id: str
    project_key: str
    name: str
    clock_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Module(TypedDict):
    id: str
    project_id: str
    module_key: str
    owner_team_member_id: str
    kloc: float
    initial_defect_quota: int
    active_defect_count: int
    quota_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TeamMember(TypedDict):
    id: str
    project_id: str
    display_name: str
    role: str
    active_workload: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Defect(TypedDict, total=False):
    id: str
    project_id: str
    module_id: str
    reporter_id: str
    assignee_id: Optional[str]
    title: str
    defect_source: str
    severity: str
    effective_severity: str
    business_impact: str
    reproduction_steps: str
    environment: Dict[str, Any]
    priority_score: int
    status: str
    sla_state: str
    reopen_count: int
    total_paused_minutes: int
    report_clock_minute: int
    first_fixed_at_minute: Optional[int]
    response_due_minute: int
    resolution_due_minute: int
    escalation_level: int
    canonical_defect_id: Optional[str]
    fix_version: Optional[str]
    final_resolution_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only — only id + created_at + entity-specific fields.
class DefectAttachment(TypedDict):
    id: str
    defect_id: str
    attachment_type: str
    filename: str
    size_bytes: int
    uploaded_by: str
    created_at: str


class DuplicateLink(TypedDict):
    id: str
    duplicate_defect_id: str
    canonical_defect_id: str
    linked_by: str
    similarity_score: float
    created_at: str


class SeverityOverride(TypedDict, total=False):
    id: str
    defect_id: str
    requested_severity: str
    justification: str
    requested_by: str
    approved_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FixRecord(TypedDict):
    id: str
    defect_id: str
    fix_version: str
    developer_id: str
    fix_summary: str
    commit_sha: str
    created_at: str


class VerificationRecord(TypedDict, total=False):
    id: str
    defect_id: str
    fix_record_id: str
    verifier_id: str
    outcome: str
    notes: Optional[str]
    created_at: str


class RegressionRun(TypedDict, total=False):
    id: str
    defect_id: str
    module_id: str
    test_suite_key: str
    started_at_minute: int
    ended_at_minute: Optional[int]
    result: Optional[str]
    impact_scope: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SLAPause(TypedDict, total=False):
    id: str
    defect_id: str
    started_at_minute: int
    ended_at_minute: Optional[int]
    reason: str
    paused_by: str
    created_at: str


class AuditEntry(TypedDict, total=False):
    id: str
    defect_id: Optional[str]
    event_type: str
    actor_id: str
    from_value: Optional[str]
    to_value: Optional[str]
    at_minute: int
    external_payload: Optional[Dict[str, Any]]
    created_at: str


__all__ = [
    "UserRole",
    "TeamMemberRole",
    "TeamMemberStatus",
    "ProjectStatus",
    "ModuleStatus",
    "DefectStatus",
    "DefectSlaState",
    "DefectSeverity",
    "DefectSource",
    "BusinessImpact",
    "SeverityOverrideStatus",
    "RegressionRunStatus",
    "RegressionRunResult",
    "SlaPauseReason",
    "VerificationOutcome",
    "AttachmentType",
    "AuditEventType",
    "ExternalEventSystem",
    "GroupByDimension",
    "DensityMode",
    "Project",
    "Module",
    "TeamMember",
    "Defect",
    "DefectAttachment",
    "DuplicateLink",
    "SeverityOverride",
    "FixRecord",
    "VerificationRecord",
    "RegressionRun",
    "SLAPause",
    "AuditEntry",
]
