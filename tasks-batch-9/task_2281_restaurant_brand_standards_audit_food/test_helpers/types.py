"""Domain types for the Restaurant Brand Standards Audit API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    BRAND_ADMIN = "BrandAdmin"
    AUDITOR = "Auditor"
    CALIBRATION_REVIEWER = "CalibrationReviewer"
    FRANCHISEE = "Franchisee"
    COMPLIANCE_INTEGRATOR = "ComplianceIntegrator"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class BrandRiskTier(str, Enum):
    BASELINE = "BASELINE"
    ELEVATED = "ELEVATED"
    SEVERE = "SEVERE"


class RegionCode(str, Enum):
    NORTHEAST = "NORTHEAST"
    SOUTHEAST = "SOUTHEAST"
    MIDWEST = "MIDWEST"
    WEST = "WEST"


class FranchiseAgreementStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    NOTICE_OF_DEFAULT = "NOTICE_OF_DEFAULT"
    CURE_PERIOD = "CURE_PERIOD"
    TERMINATION_RECOMMENDED = "TERMINATION_RECOMMENDED"


class AuditorStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    MANUAL_REVIEW = "MANUAL_REVIEW"
    RELIABILITY_BELOW_FLOOR = "RELIABILITY_BELOW_FLOOR"


class RubricVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class RubricSection(str, Enum):
    FOOD_SAFETY = "FOOD_SAFETY"
    BRAND_STANDARDS = "BRAND_STANDARDS"
    FACILITY = "FACILITY"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class VisitType(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    UNANNOUNCED = "UNANNOUNCED"
    SHADOW = "SHADOW"


class VoidReason(str, Enum):
    AUDITOR_SUSPENDED = "AUDITOR_SUSPENDED"
    RUBRIC_DEFECT = "RUBRIC_DEFECT"
    SCHEDULING_ERROR = "SCHEDULING_ERROR"


class CompositeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class Grade(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class ScoredItemStatus(str, Enum):
    SCORED = "SCORED"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    AMENDED = "AMENDED"
    UPHELD = "UPHELD"


class Severity(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class CorrectiveActionStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class VerificationOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    INFO_REQUESTED = "INFO_REQUESTED"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    UPHELD = "UPHELD"
    AMENDED = "AMENDED"
    WITHDRAWN = "WITHDRAWN"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    AMENDED = "AMENDED"


class HealthInspectionStatus(str, Enum):
    RECORDED = "RECORDED"
    DISREGARDED = "DISREGARDED"


class LetterGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    FAIL = "FAIL"


class DisregardReason(str, Enum):
    SUPERSEDED_BY_REINSPECTION = "SUPERSEDED_BY_REINSPECTION"
    WRONG_LOCATION = "WRONG_LOCATION"
    DATA_ERROR = "DATA_ERROR"


class CalibrationBand(str, Enum):
    EXCELLENT = "EXCELLENT"
    ACCEPTABLE = "ACCEPTABLE"
    MARGINAL = "MARGINAL"
    UNACCEPTABLE = "UNACCEPTABLE"


class ReliabilityVariant(str, Enum):
    ROLLING = "ROLLING"
    CERTIFICATION_REVIEW = "CERTIFICATION_REVIEW"


class EscalationEventType(str, Enum):
    REPEAT_CRITICAL = "REPEAT_CRITICAL"
    OVERDUE_CRITICAL = "OVERDUE_CRITICAL"
    CURE_ACCEPTED = "CURE_ACCEPTED"
    VOID_REVERSAL = "VOID_REVERSAL"


# --------------------------------------------------------------------------
# Fully versioned resources (PRD §2.5: id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Brand(TypedDict):
    id: str
    name: str
    brand_code: str
    unannounced_min_ratio_pct: int
    brand_risk_index: float
    brand_risk_tier: str
    location_count: int
    default_location_count: int
    created_at: str
    updated_at: str
    version: int


class Franchisee(TypedDict):
    id: str
    brand_id: str
    legal_name: str
    contact_email: str
    agreement_signed_at: str
    open_default_location_count: int
    termination_recommended: bool
    created_at: str
    updated_at: str
    version: int


class Auditor(TypedDict):
    id: str
    full_name: str
    employee_code: str
    status: str
    reliability_score: float
    certification_period_start: Optional[str]
    suspension_reason: Optional[str]
    finalized_visit_count: int
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    brand_id: str
    franchisee_id: str
    store_number: str
    region_code: str
    standing_score: float
    latest_grade: Optional[str]
    open_corrective_action_count: int
    repeat_violation_count: int
    escalation_level: int
    franchise_agreement_status: str
    cure_period_started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RubricVersion(TypedDict):
    id: str
    brand_id: str
    version_label: str
    effective_from: str
    total_points: int
    supersedes_rubric_version_id: Optional[str]
    status: str
    published_at: Optional[str]
    item_count: int
    critical_item_count: int
    created_at: str
    updated_at: str
    version: int


class AuditVisit(TypedDict):
    id: str
    location_id: str
    auditor_id: str
    rubric_version_id: str
    visit_type: str
    scheduled_start_at: str
    scheduled_end_at: str
    shadow_of_visit_id: Optional[str]
    announced_notice_hours: Optional[float]
    status: str
    started_at: Optional[str]
    submitted_at: Optional[str]
    finalized_at: Optional[str]
    food_safety_percent: Optional[float]
    brand_standards_percent: Optional[float]
    facility_percent: Optional[float]
    critical_violation_count: int
    critical_penalty_points: float
    health_component_percent: Optional[float]
    linked_health_inspection_id: Optional[str]
    composite_score: Optional[float]
    composite_variant: Optional[str]
    grade: Optional[str]
    rescore_count: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScoredItem(TypedDict):
    id: str
    visit_id: str
    rubric_item_id: str
    points_awarded: int
    original_points_awarded: int
    amended_points_awarded: Optional[int]
    effective_points_awarded: int
    is_violation: bool
    severity: str
    note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    scored_item_id: str
    location_id: str
    assigned_franchisee_id: str
    severity: str
    status: str
    due_at: str
    submitted_at: Optional[str]
    verified_at: Optional[str]
    escalated_at: Optional[str]
    submission_count: int
    rejection_count: int
    evidence_photo_count: int
    remediation_note: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    scored_item_id: str
    filed_by_franchisee_id: str
    reviewer_auditor_id: Optional[str]
    requested_points: int
    reason: str
    status: str
    filed_at: str
    info_request_count: int
    information_requested: Optional[str]
    resolution_points: Optional[int]
    rationale: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthInspection(TypedDict):
    id: str
    location_id: str
    authority_name: str
    inspection_date: str
    points_scored: int
    points_possible: int
    letter_grade: str
    status: str
    disregard_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Lighter records (PRD §2.5: only id and created_at — no updated_at, no version)
# --------------------------------------------------------------------------
class RubricItem(TypedDict):
    id: str
    rubric_version_id: str
    item_code: str
    section: str
    max_points: int
    is_critical: bool
    display_order: int
    created_at: str


class EvidencePhoto(TypedDict):
    id: str
    corrective_action_id: Optional[str]
    dispute_id: Optional[str]
    file_uri: str
    captured_at: str
    caption: Optional[str]
    uploaded_by_role: str
    created_at: str


class CalibrationRecord(TypedDict):
    id: str
    shadow_visit_id: str
    primary_visit_id: str
    auditor_id: str
    reviewer_auditor_id: str
    variance_points: float
    band: str
    reliability_delta: float
    recorded_at: str
    created_at: str


class EscalationEvent(TypedDict):
    id: str
    location_id: str
    corrective_action_id: Optional[str]
    audit_visit_id: Optional[str]
    event_type: str
    level_delta: int
    resulting_escalation_level: int
    resulting_agreement_status: str
    occurred_at: str
    created_at: str
