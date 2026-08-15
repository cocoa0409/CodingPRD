"""Domain types for the Model Risk Management API: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Resources carrying ``updated_at``/``version``
are mutable resources; the metric reading is the single append-only exception and
carries only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MODEL_OWNER = "ModelOwner"
    MODEL_VALIDATOR = "ModelValidator"
    MODEL_RISK_OFFICER = "ModelRiskOfficer"
    REGULATORY_REPORTER = "RegulatoryReporter"
    PLATFORM_ADMIN = "PlatformAdmin"


class ModelStatus(str, Enum):
    REGISTERED = "REGISTERED"
    APPROVED_FOR_USE = "APPROVED_FOR_USE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class RiskTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class Complexity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class UsageScope(str, Enum):
    SINGLE_DESK = "SINGLE_DESK"
    MULTI_DESK = "MULTI_DESK"
    ENTERPRISE = "ENTERPRISE"


class MonitoringPosture(str, Enum):
    NORMAL = "NORMAL"
    BREACHED = "BREACHED"


class DocumentationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ChangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeType(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class EngagementStatus(str, Enum):
    TESTING = "TESTING"
    COMPLETED = "COMPLETED"


class EngagementOutcome(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    EFFECTIVE_WITH_FINDINGS = "EFFECTIVE_WITH_FINDINGS"
    INEFFECTIVE = "INEFFECTIVE"


class FindingSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FindingSource(str, Enum):
    VALIDATION = "VALIDATION"
    MONITORING = "MONITORING"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class MetricDirection(str, Enum):
    ABOVE_IS_BREACH = "ABOVE_IS_BREACH"
    BELOW_IS_BREACH = "BELOW_IS_BREACH"


class MetricStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DECOMMISSIONED = "DECOMMISSIONED"


class BreachEventStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class VendorAssessmentStatus(str, Enum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class ReportType(str, Enum):
    BOARD_QUARTERLY = "BOARD_QUARTERLY"
    REGULATOR_ANNUAL = "REGULATOR_ANNUAL"


class AggregationMethod(str, Enum):
    EQUAL_WEIGHTED = "EQUAL_WEIGHTED"
    EXPOSURE_WEIGHTED = "EXPOSURE_WEIGHTED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Model(TypedDict, total=False):
    id: str
    name: str
    business_unit: str
    owner_user_id: str
    is_vendor_model: bool
    declared_complexity: str
    assessed_complexity: Optional[str]
    usage_scope: str
    exposure_amount: int
    risk_score: int
    risk_tier: str
    status: str
    monitoring_posture: str
    open_findings_count: int
    last_validated_at: Optional[str]
    validation_due_at: str
    replaced_by_model_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModelDocumentation(TypedDict, total=False):
    id: str
    model_id: str
    version_label: str
    has_development_evidence: bool
    has_testing_evidence: bool
    has_data_lineage: bool
    submitted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeRequest(TypedDict, total=False):
    id: str
    model_id: str
    change_type: str
    description: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ValidationEngagement(TypedDict, total=False):
    id: str
    model_id: str
    validator_user_id: str
    scope_conceptual_soundness: bool
    scope_outcomes_analysis: bool
    period_start: str
    period_end: str
    status: str
    outcome: Optional[str]
    assessed_complexity: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict, total=False):
    id: str
    model_id: str
    source: str
    severity: str
    title: str
    raised_by_user_id: str
    status: str
    remediation_due_at: str
    escalated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringMetric(TypedDict, total=False):
    id: str
    model_id: str
    metric_name: str
    direction: str
    threshold_value: float
    status: str
    consecutive_breach_count: int
    created_at: str
    updated_at: str
    version: int


class MetricReading(TypedDict, total=False):
    # Append-only event log: carries ONLY id + created_at plus event payload.
    # updated_at and version are absent by contract.
    id: str
    metric_id: str
    value: float
    observed_at: str
    is_breach: bool
    created_at: str


class BreachEvent(TypedDict, total=False):
    id: str
    metric_id: str
    metric_name: str
    reading_id: str
    breach_value: float
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorTransparencyAssessment(TypedDict, total=False):
    id: str
    model_id: str
    completeness_score: int
    valid_months: int
    assessed_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    report_type: str
    period_start: str
    period_end: str
    aggregation_method: str
    status: str
    total_models: int
    tier_1_count: int
    open_findings_total: int
    open_critical_count: int
    breach_event_count: int
    overdue_validation_count: int
    inventory_risk_index: float
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
