"""Domain types for the Digital Accessibility Conformance API.

Entity TypedDicts, the closed enumerations of PRD §2.10 and the role enum of
PRD §2.1, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ACCESSIBILITY_LEAD = "AccessibilityLead"
    ACCESSIBILITY_TESTER = "AccessibilityTester"
    CONFORMANCE_REVIEWER = "ConformanceReviewer"
    PRODUCT_OWNER = "ProductOwner"
    CUSTOMER_LIAISON = "CustomerLiaison"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Closed enumerations (PRD §2.10)
# ---------------------------------------------------------------------------

class StandardCode(str, Enum):
    WCAG_2_1 = "WCAG_2_1"
    WCAG_2_2 = "WCAG_2_2"
    EN_301_549 = "EN_301_549"
    SECTION_508_SW = "SECTION_508_SW"


class Surface(str, Enum):
    WEB = "WEB"
    SOFTWARE = "SOFTWARE"
    BOTH = "BOTH"


class ConformanceLevel(str, Enum):
    A = "A"
    AA = "AA"
    AAA = "AAA"


class DisabilityCategory(str, Enum):
    VISION = "VISION"
    HEARING = "HEARING"
    MOTOR = "MOTOR"
    COGNITIVE = "COGNITIVE"


class ComponentType(str, Enum):
    WEB_UI = "WEB_UI"
    DESKTOP_APP = "DESKTOP_APP"
    MOBILE_APP = "MOBILE_APP"
    AUTHORING_TOOL = "AUTHORING_TOOL"
    DOCUMENTATION = "DOCUMENTATION"


class AssessmentScope(str, Enum):
    FULL = "FULL"
    SAMPLED = "SAMPLED"
    EXCLUDED = "EXCLUDED"


class AtProfile(str, Enum):
    SCREEN_READER = "SCREEN_READER"
    KEYBOARD = "KEYBOARD"
    MAGNIFICATION = "MAGNIFICATION"


class OsPlatform(str, Enum):
    WINDOWS = "WINDOWS"
    MACOS = "MACOS"
    LINUX = "LINUX"
    ANDROID = "ANDROID"
    IOS = "IOS"


class RunMethod(str, Enum):
    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"


class SupportLevel(str, Enum):
    SUPPORTS = "SUPPORTS"
    PARTIALLY_SUPPORTS = "PARTIALLY_SUPPORTS"
    DOES_NOT_SUPPORT = "DOES_NOT_SUPPORT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class IssueSeverity(str, Enum):
    BLOCKER = "BLOCKER"
    SERIOUS = "SERIOUS"
    MODERATE = "MODERATE"
    MINOR = "MINOR"


class PublishIntent(str, Enum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class PublicationChannel(str, Enum):
    CUSTOMER_TRUST_PORTAL = "CUSTOMER_TRUST_PORTAL"
    PROCUREMENT_PACKET = "PROCUREMENT_PACKET"
    PUBLIC_WEBSITE = "PUBLIC_WEBSITE"


class QuestionnaireKind(str, Enum):
    VPAT_ACR = "VPAT_ACR"
    SECTION_508_CHECKLIST = "SECTION_508_CHECKLIST"
    EN_301_549_ANNEX = "EN_301_549_ANNEX"
    CUSTOM_RFP = "CUSTOM_RFP"


class ComplaintChannel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    WEB_FORM = "WEB_FORM"
    REGULATOR_REFERRAL = "REGULATOR_REFERRAL"


class ClosureOutcome(str, Enum):
    REMEDIATION_SCHEDULED = "REMEDIATION_SCHEDULED"
    ACCOMMODATION_PROVIDED = "ACCOMMODATION_PROVIDED"
    ACCOMMODATION_DENIED = "ACCOMMODATION_DENIED"
    NOT_A_DEFECT = "NOT_A_DEFECT"


# ---------------------------------------------------------------------------
# Lifecycle enumerations (PRD §3)
# ---------------------------------------------------------------------------

class ComponentAssessmentState(str, Enum):
    PLANNED = "PLANNED"
    IN_TESTING = "IN_TESTING"
    COMPLETE = "COMPLETE"


class DesignReviewState(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEWED_PASS = "REVIEWED_PASS"
    REVIEWED_BLOCKED = "REVIEWED_BLOCKED"


class DesignReviewDecision(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    VOID = "VOID"


class AttestationState(str, Enum):
    DRAFT = "DRAFT"
    ATTESTED = "ATTESTED"
    NEEDS_REVALIDATION = "NEEDS_REVALIDATION"
    SUPERSEDED = "SUPERSEDED"


class ReportState(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class IssueState(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    DEFERRED = "DEFERRED"
    COMMITTED = "COMMITTED"
    PUBLISHED_COMMITTED = "PUBLISHED_COMMITTED"
    RESOLVED = "RESOLVED"


class FundingState(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FULLY_FUNDED = "FULLY_FUNDED"


class RiskVariant(str, Enum):
    INTAKE_ESTIMATE = "INTAKE_ESTIMATE"
    BOARD_REVIEW = "BOARD_REVIEW"


class TrainAllocationState(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    ALLOCATED = "ALLOCATED"


class QuestionnaireReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ATTESTED = "ATTESTED"


class AccuracyStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"


class DisclosureTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class ComplaintState(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    LINKED = "LINKED"
    ACCOMMODATED = "ACCOMMODATED"
    CLOSED = "CLOSED"


class ComplaintRoute(str, Enum):
    REMEDIATION = "REMEDIATION"
    ACCOMMODATION = "ACCOMMODATION"


class AssessmentReadiness(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"


class PublicationPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

class Standard(TypedDict, total=False):
    """PRD §3.1 — accessibility standard configuration."""

    id: str
    code: str
    title: str
    surface_scope: str
    max_target_level: str
    criteria_count: int
    created_at: str
    updated_at: str
    version: int


class SuccessCriterion(TypedDict, total=False):
    """PRD §2.4 — immutable configuration: only `id` and `created_at`.

    A success criterion has no `updated_at` and no `version` field at all.
    """

    id: str
    standard_id: str
    criterion_number: str
    title: str
    level: str
    disability_categories: List[str]
    applies_to_surfaces: List[str]
    created_at: str


class Product(TypedDict, total=False):
    """PRD §3.1 — a product enrolled in the accessibility programme."""

    id: str
    name: str
    version_label: str
    standard_id: str
    target_level: str
    surface_type: str
    components_in_scope_count: int
    components_complete_count: int
    assessed_criteria_count: int
    stale_questionnaire_count: int
    correction_required_questionnaire_count: int
    overdue_committed_blocker_count: int
    accommodations_fulfilled_count: int
    conformance_index_provisional: float
    assessment_readiness: str
    publication_posture: str
    created_at: str
    updated_at: str
    version: int


class ProductComponent(TypedDict, total=False):
    """PRD §3.2 — one row of a product's assessment inventory."""

    id: str
    product_id: str
    name: str
    component_type: str
    in_scope: bool
    assessment_scope: str
    applicable_criteria_count: int
    user_reach_pct: float
    assessment_state: str
    design_review_state: str
    coverage_pct: float
    evidence_units_total: int
    validated_disability_categories: List[str]
    design_review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestEnvironment(TypedDict, total=False):
    """PRD §3.3 — an assistive-technology bench."""

    id: str
    name: str
    at_profile: str
    at_product_name: str
    os_platform: str
    reconfiguration_buffer_minutes: int
    scheduled_run_count: int
    created_at: str
    updated_at: str
    version: int


class AssessmentRun(TypedDict, total=False):
    """PRD §3.3 / §3.4 — a booking on a bench and its outcome."""

    id: str
    component_id: str
    environment_id: str
    method: str
    at_profile: str
    scheduled_start: str
    scheduled_end: str
    criteria_exercised: int
    disability_categories_validated: List[str]
    status: str
    defects_found: Optional[int]
    void_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriterionAssessment(TypedDict, total=False):
    """PRD §3.5 — one per-criterion judgement for one component."""

    id: str
    component_id: str
    criterion_id: str
    support_level: str
    evidence_run_id: Optional[str]
    remarks: Optional[str]
    attestation_state: str
    authored_by_user_id: str
    attested_by_user_id: Optional[str]
    attested_at: Optional[str]
    attestation_note: Optional[str]
    superseded_by_assessment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriterionSupportSnapshotEntry(TypedDict, total=False):
    """PRD §3.6 — one entry of a published report's per-criterion table."""

    criterion_id: str
    rolled_support_level: Optional[str]
    weight: float


class ConformanceReport(TypedDict, total=False):
    """PRD §3.7 — a customer-facing conformance report."""

    id: str
    product_id: str
    standard_id: str
    report_title: str
    state: str
    pinned_assessment_ids: List[str]
    pinned_assessment_versions: List[int]
    criterion_support_snapshot: List[CriterionSupportSnapshotEntry]
    conformance_index_certified: Optional[float]
    published_issue_count: int
    change_request_count: int
    publication_channel: Optional[str]
    published_at: Optional[str]
    withdrawal_reason: Optional[str]
    superseded_by_report_id: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseTrain(TypedDict, total=False):
    """PRD §3.9 — the remediation roadmap's unit of delivery."""

    id: str
    name: str
    window_start: str
    window_end: str
    freeze_days: int
    effort_capacity_points: int
    remediation_budget_cents: int
    committed_effort_points: int
    unallocated_cents: int
    allocation_state: str
    created_at: str
    updated_at: str
    version: int


class KnownIssue(TypedDict, total=False):
    """PRD §3.9 — a known accessibility defect."""

    id: str
    product_id: str
    component_id: str
    criterion_id: str
    severity: str
    summary: str
    effort_points: int
    target_remediation_date: str
    publish_intent: str
    state: str
    release_train_id: Optional[str]
    public_target_date: Optional[str]
    published_report_id: Optional[str]
    resolution_run_id: Optional[str]
    triage_note: Optional[str]
    board_review_note: Optional[str]
    resolution_note: Optional[str]
    funded_cents: int
    funding_state: str
    linked_complaint_count: int
    risk_variant: str
    risk_score: float
    created_at: str
    updated_at: str
    version: int


class QuestionnaireResponse(TypedDict, total=False):
    """PRD §3.10 — a customer procurement questionnaire response."""

    id: str
    product_id: str
    report_id: str
    customer_name: str
    questionnaire_kind: str
    answers_summary: str
    review_status: str
    accuracy_status: str
    disclosure_debt: float
    disclosure_tier: str
    revision_count: int
    submitted_at: Optional[str]
    last_attested_at: Optional[str]
    update_due_at: Optional[str]
    correction_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    """PRD §3.11 — complaint or accommodation intake."""

    id: str
    product_id: str
    component_id: Optional[str]
    criterion_id: Optional[str]
    channel: str
    description: str
    disability_category: str
    state: str
    route: Optional[str]
    linked_issue_id: Optional[str]
    requested_accommodation: Optional[str]
    needed_by_date: Optional[str]
    accommodation_fulfilled_at: Optional[str]
    closure_outcome: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
