"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4).

Every resource carries the common system-managed properties of PRD §2.4
(`id`, `created_at`, `updated_at`, `version`). One naming note from PRD §2.4:
on a Component, `version` is the client-supplied upstream package version
string, not the system-managed revision counter.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    LEGAL_COUNSEL = "LegalCounsel"
    ENGINEERING_MANAGER = "EngineeringManager"
    SECURITY_ANALYST = "SecurityAnalyst"
    RELEASE_MANAGER = "ReleaseManager"
    CISO = "CISO"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Enum vocabularies (PRD §2.7, §3) ─────────────────

class DistributionModel(str, Enum):
    SAAS = "SaaS"
    ON_PREMISE = "ON_PREMISE"
    EMBEDDED = "EMBEDDED"
    MOBILE_APP = "MOBILE_APP"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"


class LicenseClassification(str, Enum):
    PERMISSIVE = "PERMISSIVE"
    WEAK_COPYLEFT = "WEAK_COPYLEFT"
    STRONG_COPYLEFT = "STRONG_COPYLEFT"
    RESTRICTED = "RESTRICTED"
    PROHIBITED = "PROHIBITED"


class ScanTool(str, Enum):
    SYFT = "SYFT"
    ORT = "ORT"
    SCANCODE = "SCANCODE"
    FOSSOLOGY = "FOSSOLOGY"
    COMMERCIAL_VENDOR_X = "COMMERCIAL_VENDOR_X"


class ScanScope(str, Enum):
    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"
    TRANSITIVE = "TRANSITIVE"
    DIRECT_ONLY = "DIRECT_ONLY"


class ScanStatus(str, Enum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    RESOLVING = "RESOLVING"
    SCANNING_LICENSES = "SCANNING_LICENSES"
    SCORING = "SCORING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BomStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class BomPosture(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class DependencyScope(str, Enum):
    RUNTIME = "RUNTIME"
    BUILD_TIME = "BUILD_TIME"
    TEST = "TEST"
    OPTIONAL = "OPTIONAL"
    DEV = "DEV"


class ObligationDetermination(str, Enum):
    NONE = "NONE"
    ATTRIBUTION_ONLY = "ATTRIBUTION_ONLY"
    SOURCE_OFFER = "SOURCE_OFFER"
    SOURCE_DISCLOSURE = "SOURCE_DISCLOSURE"
    FULL_SOURCE_DISCLOSURE = "FULL_SOURCE_DISCLOSURE"
    PROHIBITED_USE = "PROHIBITED_USE"


class ObligationType(str, Enum):
    ATTRIBUTION = "ATTRIBUTION"
    SOURCE_OFFER = "SOURCE_OFFER"
    SOURCE_DELIVERY = "SOURCE_DELIVERY"
    LICENSE_TEXT = "LICENSE_TEXT"
    NOTICE_FILE = "NOTICE_FILE"
    COPYLEFT_COMPLIANCE = "COPYLEFT_COMPLIANCE"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    WAIVED = "WAIVED"
    OVERDUE = "OVERDUE"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    ENGINEERING_REVIEW = "ENGINEERING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class LegalDecision(str, Enum):
    PENDING = "PENDING"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CONDITIONAL = "CONDITIONAL"


class EngineeringDecision(str, Enum):
    PENDING = "PENDING"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    MITIGATED = "MITIGATED"
    REMEDIATED = "REMEDIATED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    WONT_FIX = "WONT_FIX"


class RemediationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class GateStatus(str, Enum):
    OPEN = "OPEN"
    EVALUATING = "EVALUATING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BYPASSED = "BYPASSED"
    EXPIRED = "EXPIRED"


class EvaluationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"


class PlanType(str, Enum):
    UPGRADE = "UPGRADE"
    REPLACE = "REPLACE"
    PATCH = "PATCH"
    MITIGATE_CONFIG = "MITIGATE_CONFIG"
    ACCEPT_RISK = "ACCEPT_RISK"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


class AuditType(str, Enum):
    M_AND_A = "M_AND_A"
    IPO_READINESS = "IPO_READINESS"
    CUSTOMER_DUE_DILIGENCE = "CUSTOMER_DUE_DILIGENCE"
    REGULATORY_INQUIRY = "REGULATORY_INQUIRY"


class AuditStatus(str, Enum):
    INITIATED = "INITIATED"
    SCOPING = "SCOPING"
    DATA_COLLECTION = "DATA_COLLECTION"
    ANALYSIS = "ANALYSIS"
    REPORT_DRAFT = "REPORT_DRAFT"
    REPORT_FINAL = "REPORT_FINAL"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (PRD §2.4 common properties) ───

class Product(TypedDict, total=False):
    id: str
    product_code: str
    product_name: str
    distribution_model: str
    compliance_posture: str
    posture_version: int
    total_dependency_count: int
    copyleft_dependency_count: int
    restricted_dependency_count: int
    high_severity_vulnerability_count: int
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    # PRD §2.4 naming note: on a Component, `version` is the client-supplied
    # upstream package version string, not the system revision counter.
    id: str
    package_url: str
    component_name: str
    version: str
    declared_license_spdx: str
    discovered_license_spdx: Optional[str]
    license_policy_classification: Optional[str]
    policy_override_classification: Optional[str]
    effective_classification: Optional[str]
    source_download_url: Optional[str]
    copyright_notice: Optional[str]
    created_at: str
    updated_at: str


class DependencyScan(TypedDict, total=False):
    id: str
    product_id: str
    scan_tool: str
    scan_scope: str
    status: str
    raw_manifest_hash: str
    components_discovered: int
    components_resolved: int
    license_scan_coverage_pct: float
    created_at: str
    updated_at: str
    version: int


class BillOfMaterials(TypedDict, total=False):
    id: str
    product_id: str
    scan_id: str
    version_label: str
    status: str
    bom_posture: Optional[str]
    total_components: int
    copyleft_components: int
    restricted_components: int
    prohibited_components: int
    notice_file_generated: bool
    notice_file_hash: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BomEntry(TypedDict, total=False):
    id: str
    bom_id: str
    component_id: str
    dependency_scope: str
    is_direct: bool
    dependency_depth: int
    parent_entry_id: Optional[str]
    obligation_determination: Optional[str]
    obligation_fulfilled: bool
    vulnerability_severity_max: str
    created_at: str
    updated_at: str
    version: int


class LicenseApprovalRequest(TypedDict, total=False):
    id: str
    product_id: str
    component_id: str
    bom_entry_id: str
    request_reason: Optional[str]
    risk_acknowledgment: bool
    status: str
    legal_reviewer_id: Optional[str]
    engineering_reviewer_id: Optional[str]
    legal_decision: str
    legal_conditions: Optional[str]
    engineering_decision: str
    final_decision: Optional[str]
    decision_effective_at: Optional[str]
    expiry_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObligationTicket(TypedDict, total=False):
    id: str
    product_id: str
    bom_entry_id: str
    obligation_type: str
    due_at: str
    status: str
    fulfillment_evidence_uri: Optional[str]
    waiver_reason: Optional[str]
    waived_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vulnerability(TypedDict, total=False):
    id: str
    cve_id: str
    severity: str
    cvss_score: float
    published_at: str
    affected_package_url: str
    fixed_in_version: Optional[str]
    license_change_flag: bool
    new_license_spdx: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VulnerabilityFinding(TypedDict, total=False):
    id: str
    product_id: str
    bom_entry_id: str
    vulnerability_id: str
    detected_at: str
    status: str
    remediation_deadline: Optional[str]
    remediation_component_id: Optional[str]
    remediation_status: str
    verification_evidence_uri: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseGate(TypedDict, total=False):
    id: str
    product_id: str
    bom_id: str
    release_version: str
    gate_status: str
    evaluation_result: Optional[str]
    blocking_findings_count: Optional[int]
    warning_findings_count: Optional[int]
    notice_file_attached: bool
    obligations_fulfilled_pct: Optional[float]
    bypass_reason: Optional[str]
    bypass_approved_by: Optional[str]
    evaluation_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    product_id: str
    finding_id: str
    plan_type: str
    target_component_id: Optional[str]
    target_version: Optional[str]
    migration_effort_days: int
    status: str
    actual_completion_at: Optional[str]
    verification_scan_id: Optional[str]
    license_compatibility_verified: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict, total=False):
    id: str
    product_id: str
    audit_type: str
    requesting_party: str
    scope_description: str
    status: str
    target_completion_at: str
    actual_completion_at: Optional[str]
    findings_summary: Optional[str]
    critical_findings_count: Optional[int]
    report_hash: Optional[str]
    created_at: str
    updated_at: str
    version: int
