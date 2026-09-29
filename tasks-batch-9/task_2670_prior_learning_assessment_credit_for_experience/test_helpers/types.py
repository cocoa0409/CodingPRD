"""Typed shapes and enumerations for the Prior Learning Assessment API.

Field sets follow PRD S2.4: LearningOutcome and Artifact carry only ``id`` and
``created_at``; every other resource carries the full quartet of ``id``,
``created_at``, ``updated_at`` and ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD S2.1 - spelled exactly as the contract spells them)
# --------------------------------------------------------------------------
class Role:
    STUDENT = "Student"
    PLA_COORDINATOR = "PlaCoordinator"
    FACULTY_ASSESSOR = "FacultyAssessor"
    APPEAL_REVIEWER = "AppealReviewer"
    ARTICULATION_OFFICER = "ArticulationOfficer"
    REGISTRAR = "Registrar"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class ProgramStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CourseLevel:
    LOWER = "LOWER"
    UPPER = "UPPER"


class SourceType:
    CREDIT_BY_EXAM = "CREDIT_BY_EXAM"
    PORTFOLIO = "PORTFOLIO"
    MILITARY_TRAINING = "MILITARY_TRAINING"
    INDUSTRY_CREDENTIAL = "INDUSTRY_CREDENTIAL"


class EnrollmentStatus:
    MATRICULATED = "MATRICULATED"
    APPLICANT = "APPLICANT"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class AssessorStatus:
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class RecommendationStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class RuleStatus:
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class AssessmentStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SCORED = "SCORED"
    CAP_BLOCKED = "CAP_BLOCKED"
    AWARDED = "AWARDED"
    DENIED = "DENIED"
    APPEAL_PENDING = "APPEAL_PENDING"
    DENIED_FINAL = "DENIED_FINAL"
    WITHDRAWN = "WITHDRAWN"


class FeeStatus:
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WAIVED = "WAIVED"
    REFUNDED = "REFUNDED"
    RETAINED = "RETAINED"


class CreditStatus:
    NOT_POSTED = "NOT_POSTED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PortfolioStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    LOCKED = "LOCKED"
    VOIDED = "VOIDED"


class AssignmentStatus:
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SCORING_COMPLETE = "SCORING_COMPLETE"
    REVOKED = "REVOKED"


class AppealStatus:
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    REMANDED = "REMANDED"


class SlaState:
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class PriorityTier:
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class Recommendation:
    PASS = "PASS"
    FAIL = "FAIL"


class Alignment:
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"


class ArtifactType:
    """PRD S3.4 domain for ``artifact_type``."""

    WORK_PRODUCT = "WORK_PRODUCT"
    EMPLOYER_LETTER = "EMPLOYER_LETTER"
    TRAINING_CERTIFICATE = "TRAINING_CERTIFICATE"
    LICENSE = "LICENSE"
    MILITARY_RECORD = "MILITARY_RECORD"
    SUPERVISOR_EVALUATION = "SUPERVISOR_EVALUATION"


class PaymentMethod:
    """PRD S3.10 payment ``method`` domain."""

    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"
    THIRD_PARTY = "THIRD_PARTY"
    FINANCIAL_AID = "FINANCIAL_AID"


class HoldReason:
    PLA_CAP = "PLA_CAP"
    UPPER_DIVISION_CAP = "UPPER_DIVISION_CAP"
    ARTICULATION_SUSPENDED = "ARTICULATION_SUSPENDED"
    NO_ELIGIBLE_ASSESSOR = "NO_ELIGIBLE_ASSESSOR"


class SuspendReason:
    MANUAL_REVIEW = "MANUAL_REVIEW"
    RECOMMENDATION_RETIRED = "RECOMMENDATION_RETIRED"


class SelectionReason:
    EXPLICIT = "EXPLICIT"
    AUTO_SELECTED = "AUTO_SELECTED"
    AUTO_REPLACEMENT = "AUTO_REPLACEMENT"


class RevokeReason:
    SLA_BREACH = "SLA_BREACH"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CLAIM_WITHDRAWN = "CLAIM_WITHDRAWN"
    CAP_BLOCKED = "CAP_BLOCKED"
    ASSESSOR_DECLINED = "ASSESSOR_DECLINED"


class AuditStatus:
    ELIGIBLE = "ELIGIBLE"
    DEFICIENT_CREDITS = "DEFICIENT_CREDITS"
    RESIDENCY_DEFICIENT = "RESIDENCY_DEFICIENT"
    PLA_CAP_VIOLATION = "PLA_CAP_VIOLATION"


class AppealDecision:
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    REMANDED = "REMANDED"


class InvoiceLineKind:
    BASE_ASSESSMENT_FEE = "BASE_ASSESSMENT_FEE"
    PER_CREDIT_FEE = "PER_CREDIT_FEE"
    ARTIFACT_TIER_SURCHARGE = "ARTIFACT_TIER_SURCHARGE"
    RUSH_SURCHARGE = "RUSH_SURCHARGE"
    APPEAL_FILING_FEE = "APPEAL_FILING_FEE"
    SLA_SERVICE_CREDIT = "SLA_SERVICE_CREDIT"


class InvoiceLine(TypedDict):
    """PRD S3.10: ``lines`` holds objects of ``line_type`` and ``amount_cents``."""

    line_type: str
    amount_cents: int


class OutcomeMapping(TypedDict):
    """PRD S3.4 artifact ``outcome_mappings`` entry."""

    learning_outcome_id: str
    alignment: str


# --------------------------------------------------------------------------
# Resource shapes. Every resource below carries the full quartet of
# ``id``, ``created_at``, ``updated_at`` and ``version`` except
# ``LearningOutcome`` and ``Artifact``, which carry only ``id`` and
# ``created_at`` (PRD S3.1 and PRD S3.4).
# --------------------------------------------------------------------------
class Program(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_code: str
    title: str
    total_credits_required: int
    residency_min_credits: int
    pla_max_credits: int
    pla_max_pct_bp: int
    pla_upper_division_max_credits: int
    pla_pass_threshold_bp: Optional[int]
    allowed_source_types: List[str]
    status: str
    effective_pla_cap_credits: int


class Course(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    course_code: str
    title: str
    department_code: str
    credits: int
    level: str
    pla_eligible: bool
    outcome_count: int


class LearningOutcome(TypedDict):
    id: str
    created_at: str
    course_id: str
    outcome_code: str
    description: str
    weight_bp: int
    mastery_threshold_bp: int


class CredentialRecommendation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    source_type: str
    credential_code: str
    title: str
    issuing_body: str
    recommended_credits: int
    recommended_level: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    approved_rule_count: int
    terms_version: int
    retire_reason: Optional[str]


class ArticulationRule(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    recommendation_id: str
    course_id: str
    awarded_credits: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    pinned_recommendation_version: Optional[int]
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    suspend_reason: Optional[str]


class Student(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    student_number: str
    full_name: str
    program_id: str
    enrollment_status: str
    transfer_credits_accepted: int
    institutional_credits_earned: int
    pla_credits_reserved: int
    pla_credits_awarded: int
    pla_credits_posted: int
    pla_upper_division_committed: int
    fee_paid_net_cents: int


class FacultyAssessor(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_number: str
    full_name: str
    department_code: str
    credential_rank: int
    max_concurrent_assignments: int
    appeal_panel_member: bool
    status: str
    active_assignment_count: int


class PlaClaim(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    student_id: str
    course_id: str
    articulation_rule_id: Optional[str]
    supersedes_claim_id: Optional[str]
    claim_number: int
    source_type: str
    credits_requested: int
    credits_awarded: Optional[int]
    attempt_date: Optional[str]
    rush_requested: bool
    priority_tier: str
    assessment_status: str
    fee_status: str
    credit_status: str
    provisional_coverage_bp: Optional[int]
    verified_coverage_bp: Optional[int]
    assessor_recommendation: Optional[str]
    revision_round: int
    sla_breach_count: int
    appeal_count: int
    hold_reason: Optional[str]
    denial_reason: Optional[str]
    appeal_deadline_at: Optional[str]
    submitted_at: Optional[str]
    posted_term: Optional[str]
    posted_credits: Optional[int]


class Portfolio(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    claim_id: str
    narrative: Optional[str]
    status: str
    artifact_count: int
    provisional_coverage_bp: Optional[int]
    verified_coverage_bp: Optional[int]
    revision_round: int
    submitted_at: Optional[str]


class Artifact(TypedDict):
    id: str
    created_at: str
    portfolio_id: str
    artifact_type: str
    title: str
    description: Optional[str]
    evidence_uri: str
    outcome_mappings: List[OutcomeMapping]


class AssessorAssignment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    claim_id: str
    assessor_id: str
    status: str
    selection_reason: str
    assigned_at: str
    accepted_at: Optional[str]
    sla_hours: int
    due_at: str
    at_risk_at: str
    elapsed_bp: int
    sla_state: str
    rubric_submitted_at: Optional[str]
    recommendation: Optional[str]
    verified_coverage_bp: Optional[int]
    revoke_reason: Optional[str]
    decline_reason: Optional[str]


class RubricScore(TypedDict):
    id: str
    created_at: str
    assignment_id: str
    learning_outcome_id: str
    points_awarded: int
    points_possible: int
    score_ratio_bp: int
    outcome_met: bool
    narrative: Optional[str]


class Appeal(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    claim_id: str
    grounds: str
    status: str
    reviewer_assessor_id: Optional[str]
    filed_at: str
    assigned_at: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    prior_scorer_assessor_ids: List[str]


class FeeInvoice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    claim_id: str
    student_id: str
    lines: List[InvoiceLine]
    subtotal_cents: int
    discount_bp: int
    discount_cents: int
    total_cents: int
    paid_cents: int
    refunded_cents: int
    waived_cents: int
    balance_due_cents: int
    aid_eligible: bool
    recompute_count: int


JsonDict = Dict[str, Any]
