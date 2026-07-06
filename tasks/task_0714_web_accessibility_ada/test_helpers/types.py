"""Domain types: entity TypedDicts, status enums, role enum (Web Accessibility / ADA Compliance API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ORG_ADMIN = "OrgAdmin"
    AUDIT_ENGINEER = "AuditEngineer"
    REMEDIATION_VENDOR = "RemediationVendor"
    COMPLIANCE_MANAGER = "ComplianceManager"


# ─── Status enums ─────────────────────────────────────────────────────────
class SubscriptionStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SubscriptionTier(str, Enum):
    SCAN = "SCAN"
    MONITOR = "MONITOR"
    MANAGED = "MANAGED"


class AuditPosture(str, Enum):
    UNSCANNED = "UNSCANNED"
    CLEAN = "CLEAN"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class ScanStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WcagLevel(str, Enum):
    A = "A"
    AA = "AA"
    AAA = "AAA"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    SERIOUS = "SERIOUS"
    MODERATE = "MODERATE"
    MINOR = "MINOR"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    IN_REMEDIATION = "IN_REMEDIATION"
    RETEST_PENDING = "RETEST_PENDING"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    WONT_FIX_ACCEPTED = "WONT_FIX_ACCEPTED"


class RemediationTaskStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RetestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class VpatStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class ConformanceLevel(str, Enum):
    WCAG_AA_FULL = "WCAG_AA_FULL"
    WCAG_AA_PARTIAL = "WCAG_AA_PARTIAL"
    WCAG_A = "WCAG_A"
    NON_CONFORMANT = "NON_CONFORMANT"


class LegalDemandStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RESPONDING = "RESPONDING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class TrainingStatus(str, Enum):
    ENROLLED = "ENROLLED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class CertificationStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Entities with common_fields: true carry id + created_at + updated_at + version.

class Organization(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    account_credit_cents: int
    open_legal_demand_count: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    organization_id: str
    tier: str
    status: str
    monthly_invoice_cents: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    organization_id: str
    url: str
    audited_page_count: int
    audit_posture: str
    risk_exposure_score: float
    created_at: str
    updated_at: str
    version: int


class Scan(TypedDict):
    id: str
    site_id: str
    wcag_target_level: str
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    provisional_conformance_score: Optional[float]
    finding_count: int
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    scan_id: str
    site_id: str
    wcag_criterion: str
    severity: str
    status: str
    sla_due_at: str
    is_overdue: bool
    created_at: str
    updated_at: str
    version: int


class RemediationTask(TypedDict):
    id: str
    finding_id: str
    assigned_vendor_id: str
    supersedes_task_id: Optional[str]
    status: str
    estimated_effort_hours: float
    created_at: str
    updated_at: str
    version: int


class VpatReport(TypedDict):
    id: str
    site_id: str
    source_scan_id: str
    pinned_scan_version: int
    status: str
    certified_conformance_score: Optional[float]
    conformance_level: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegalDemand(TypedDict):
    id: str
    site_id: str
    claimant_name: str
    status: str
    response_due_at: str
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict):
    id: str
    organization_id: str
    learner_email: str
    status: str
    score_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    site_id: str
    vpat_report_id: str
    status: str
    badge_token: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


# Entities with common_fields: false — immutable event records, id + created_at ONLY.
# No updated_at, no version (PRD §2.4).

class RetestRun(TypedDict):
    id: str
    finding_id: str
    remediation_task_id: str
    outcome: str
    tested_at: str
    created_at: str


class MonitoringCheck(TypedDict):
    id: str
    site_id: str
    regressions_found: int
    checked_at: str
    created_at: str
