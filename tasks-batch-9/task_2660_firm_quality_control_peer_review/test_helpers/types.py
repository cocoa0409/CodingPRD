"""Domain types for the Firm Quality Control & Peer Review API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every entity in this system exposes the full set of ``id``,
``created_at``, ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    FIRM_MANAGING_PARTNER = "FirmManagingPartner"
    ENGAGEMENT_PARTNER = "EngagementPartner"
    QUALITY_CONTROL_DIRECTOR = "QualityControlDirector"
    ENGAGEMENT_QUALITY_REVIEWER = "EngagementQualityReviewer"
    PEER_REVIEWER = "PeerReviewer"
    PEER_REVIEW_COMMITTEE = "PeerReviewCommittee"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class RiskPosture(str, Enum):
    STABLE = "STABLE"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class EnrolledProgram(str, Enum):
    AICPA_PRC = "AICPA_PRC"
    STATE_BOARD = "STATE_BOARD"


class PeerReviewRating(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    PASS_WITH_DEFICIENCY = "PASS_WITH_DEFICIENCY"
    FAIL = "FAIL"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Designation(str, Enum):
    MANAGING_PARTNER = "MANAGING_PARTNER"
    ENGAGEMENT_PARTNER = "ENGAGEMENT_PARTNER"
    QC_DIRECTOR = "QC_DIRECTOR"
    EQ_REVIEWER = "EQ_REVIEWER"


class IndustrySpecialization(str, Enum):
    EBP = "EBP"
    GOVERNMENT = "GOVERNMENT"
    BROKER_DEALER = "BROKER_DEALER"
    NONPROFIT = "NONPROFIT"
    MANUFACTURING = "MANUFACTURING"


class EngagementType(str, Enum):
    AUDIT = "AUDIT"
    REVIEW = "REVIEW"
    ATTESTATION = "ATTESTATION"
    ERISA_AUDIT = "ERISA_AUDIT"
    SINGLE_AUDIT = "SINGLE_AUDIT"
    BROKER_DEALER = "BROKER_DEALER"


class EngagementWorkflowState(str, Enum):
    PLANNING = "PLANNING"
    FIELDWORK = "FIELDWORK"
    EQR_PENDING = "EQR_PENDING"
    EQR_CLEARED = "EQR_CLEARED"
    REPORT_RELEASED = "REPORT_RELEASED"


class EngagementFileState(str, Enum):
    OPEN = "OPEN"
    ASSEMBLED = "ASSEMBLED"
    LOCKED = "LOCKED"


class SqmComponent(str, Enum):
    GOVERNANCE_LEADERSHIP = "GOVERNANCE_LEADERSHIP"
    ETHICAL_REQUIREMENTS = "ETHICAL_REQUIREMENTS"
    ACCEPTANCE_CONTINUANCE = "ACCEPTANCE_CONTINUANCE"
    ENGAGEMENT_PERFORMANCE = "ENGAGEMENT_PERFORMANCE"
    RESOURCES = "RESOURCES"
    INFORMATION_COMMUNICATION = "INFORMATION_COMMUNICATION"
    MONITORING_REMEDIATION = "MONITORING_REMEDIATION"


class QualityRiskState(str, Enum):
    DRAFT = "DRAFT"
    ASSESSED = "ASSESSED"
    RESPONDED = "RESPONDED"
    EVALUATED = "EVALUATED"


class EvaluationBasis(str, Enum):
    NONE = "NONE"
    DESIGN_BASIS = "DESIGN_BASIS"
    OPERATING_BASIS = "OPERATING_BASIS"


class SeverityBand(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResponseType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    DETECTIVE = "DETECTIVE"


class ResponseStatus(str, Enum):
    DESIGNED = "DESIGNED"
    TESTED = "TESTED"
    SUPERSEDED = "SUPERSEDED"


class DesignEffectiveness(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    EFFECTIVE = "EFFECTIVE"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"


class OperatingEffectiveness(str, Enum):
    NOT_TESTED = "NOT_TESTED"
    EFFECTIVE = "EFFECTIVE"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"


class QualityReviewState(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    CONCERNS_RAISED = "CONCERNS_RAISED"
    CONCURRED = "CONCURRED"
    WITHDRAWN = "WITHDRAWN"


class InspectionState(str, Enum):
    PLANNING = "PLANNING"
    SELECTION_COMPLETE = "SELECTION_COMPLETE"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_CLASSIFIED = "FINDINGS_CLASSIFIED"
    CONCLUDED = "CONCLUDED"


class SeverityIndexBasis(str, Enum):
    NONE = "NONE"
    ENGAGEMENT_WEIGHTED = "ENGAGEMENT_WEIGHTED"
    FIRM_PERVASIVE = "FIRM_PERVASIVE"


class SelectionReason(str, Enum):
    MUST_SELECT_ERISA_AUDIT = "MUST_SELECT_ERISA_AUDIT"
    MUST_SELECT_SINGLE_AUDIT = "MUST_SELECT_SINGLE_AUDIT"
    MUST_SELECT_BROKER_DEALER = "MUST_SELECT_BROKER_DEALER"
    MUST_SELECT_PARTNER_COVERAGE = "MUST_SELECT_PARTNER_COVERAGE"
    RISK_BASED = "RISK_BASED"


class FindingState(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    RCA_PENDING = "RCA_PENDING"
    RCA_COMPLETE = "RCA_COMPLETE"
    REMEDIATION_ASSIGNED = "REMEDIATION_ASSIGNED"
    REMEDIATED = "REMEDIATED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


class FindingClassification(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    OBSERVATION = "OBSERVATION"
    DEFICIENCY = "DEFICIENCY"
    SIGNIFICANT_DEFICIENCY = "SIGNIFICANT_DEFICIENCY"
    MATERIAL_FAILURE = "MATERIAL_FAILURE"


class Pervasiveness(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    ISOLATED = "ISOLATED"
    SYSTEMIC = "SYSTEMIC"


class RcaMethod(str, Enum):
    FIVE_WHYS = "FIVE_WHYS"
    FISHBONE = "FISHBONE"
    PARETO = "PARETO"


class RootCauseCategory(str, Enum):
    SUPERVISION_REVIEW = "SUPERVISION_REVIEW"
    TECHNICAL_COMPETENCE = "TECHNICAL_COMPETENCE"
    RESOURCE_ALLOCATION = "RESOURCE_ALLOCATION"
    TONE_AT_THE_TOP = "TONE_AT_THE_TOP"
    METHODOLOGY_TOOLING = "METHODOLOGY_TOOLING"
    CLIENT_ACCEPTANCE = "CLIENT_ACCEPTANCE"


class RcaState(str, Enum):
    DRAFTED = "DRAFTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class RemediationPlanState(str, Enum):
    DRAFTED = "DRAFTED"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class CompletenessTier(str, Enum):
    NONE = "NONE"
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"
    STRONG = "STRONG"


class MustSelectCategory(str, Enum):
    ERISA_AUDIT = "ERISA_AUDIT"
    SINGLE_AUDIT = "SINGLE_AUDIT"
    BROKER_DEALER = "BROKER_DEALER"
    GOVERNMENTAL = "GOVERNMENTAL"
    PUBLIC_INTEREST = "PUBLIC_INTEREST"


class ReviewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PeerReviewType(str, Enum):
    SYSTEM_REVIEW = "SYSTEM_REVIEW"
    ENGAGEMENT_REVIEW = "ENGAGEMENT_REVIEW"


class PeerReviewState(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLANNING = "PLANNING"
    SCOPE_SET = "SCOPE_SET"
    FIELDWORK = "FIELDWORK"
    RATING_DRAFTED = "RATING_DRAFTED"
    REPORT_ISSUED = "REPORT_ISSUED"
    CORRECTIVE_ACTION_REQUIRED = "CORRECTIVE_ACTION_REQUIRED"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"


class PeerReviewSelectionStatus(str, Enum):
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"


class Disposition(str, Enum):
    NONE = "NONE"
    NO_MATTER = "NO_MATTER"
    FFC = "FFC"
    DEFICIENCY = "DEFICIENCY"
    SIGNIFICANT_DEFICIENCY = "SIGNIFICANT_DEFICIENCY"


class CorrectiveActionStatus(str, Enum):
    REQUIRED = "REQUIRED"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ActionCode(str, Enum):
    FFC_LETTER = "FFC_LETTER"
    MONITORING_VISIT = "MONITORING_VISIT"
    CPE_COURSEWORK = "CPE_COURSEWORK"
    PREISSUANCE_REVIEW = "PREISSUANCE_REVIEW"
    ACCELERATED_REVIEW = "ACCELERATED_REVIEW"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Firm(TypedDict):
    id: str
    legal_name: str
    state_code: str
    aa_hours_last_year: int
    enrolled_program: str
    peer_review_year_end: str
    risk_posture: str
    open_deficiency_count: int
    open_material_failure_count: int
    critical_risk_count: int
    last_peer_review_rating: str
    prior_reviewer_ids: List[str]
    unassigned_review_flag: bool
    created_at: str
    updated_at: str
    version: int


class Partner(TypedDict):
    id: str
    firm_id: str
    full_name: str
    cpa_license_state: str
    designations: List[str]
    industry_specializations: List[str]
    cpe_hours_last_3y: int
    prior_engagement_team_clients: List[dict]
    independence_conflict_client_names: List[str]
    status: str
    eqr_eligible: bool
    open_eqr_count: int
    open_engagement_count: int
    last_inspected_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    firm_id: str
    client_name: str
    engagement_type: str
    period_end: str
    engagement_partner_id: str
    is_public_interest: bool
    is_first_year_client: bool
    prior_finding_count_3y: int
    risk_score: int
    eqr_required: bool
    workflow_state: str
    file_state: str
    eqr_concurred_at: Optional[str]
    report_release_date: Optional[str]
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class QualityRisk(TypedDict):
    id: str
    firm_id: str
    component: str
    quality_objective_code: str
    risk_statement: str
    likelihood: int
    impact: int
    inherent_risk_score: int
    residual_risk_score: Optional[float]
    evaluation_basis: str
    severity_band: str
    response_count: int
    reopen_count: int
    state: str
    created_at: str
    updated_at: str
    version: int


class RiskResponse(TypedDict):
    id: str
    quality_risk_id: str
    response_type: str
    description: str
    status: str
    design_effectiveness: str
    operating_effectiveness: str
    tested_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngagementQualityReview(TypedDict):
    id: str
    engagement_id: str
    reviewer_partner_id: str
    objectivity_attested: bool
    cooling_off_days_at_assignment: Optional[int]
    assigned_at: str
    concluded_at: Optional[str]
    concern_round_count: int
    last_concern_summary: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class InternalInspection(TypedDict):
    id: str
    firm_id: str
    inspection_year: int
    target_engagement_count: int
    engagements_selected_count: int
    must_select_eligible_count: int
    must_select_selected_count: int
    must_select_coverage_pct: float
    severity_index_basis: str
    deficiency_severity_index: Optional[float]
    concluded_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class InspectionSelection(TypedDict):
    id: str
    inspection_id: str
    engagement_id: str
    selection_reason: str
    is_must_select: bool
    selected_rank: int
    finding_count: int
    weighted_points: float
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict):
    id: str
    selection_id: str
    title: str
    sqm_component: str
    prior_cycle_recurrence: bool
    classification: str
    pervasiveness: str
    affects_report_conclusion: bool
    class_points: int
    verified_at: Optional[str]
    reopen_count: int
    state: str
    created_at: str
    updated_at: str
    version: int


class RootCauseAnalysis(TypedDict):
    id: str
    finding_id: str
    method: str
    root_cause_category: str
    contributing_factor_count: int
    narrative: str
    depth_score: float
    recurrence_flag: bool
    validated_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict):
    id: str
    finding_id: str
    root_cause_analysis_id: str
    owner_partner_id: str
    target_completion_date: str
    action_count: int
    action_specificity_score: float
    completed_action_count: int
    raw_completeness: Optional[float]
    completeness_tier: str
    acceptance_score: Optional[float]
    return_count: int
    accepted_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class PeerReviewer(TypedDict):
    id: str
    reviewer_firm_name: str
    license_state: str
    accepts_out_of_state: bool
    qualified_categories: List[str]
    independence_conflict_firm_names: List[str]
    max_concurrent_reviews: int
    experience_hours: int
    status: str
    active_review_count: int
    committed_hours_balance: int
    created_at: str
    updated_at: str
    version: int


class PeerReview(TypedDict):
    id: str
    firm_id: str
    review_type: str
    year_end: str
    scheduled_window_start: str
    scheduled_window_end: str
    assigned_reviewer_id: Optional[str]
    rating: str
    is_follow_up: bool
    prior_peer_review_id: Optional[str]
    must_select_categories: List[str]
    total_scope_hours: Optional[int]
    unallocated_hours: Optional[int]
    scope_limitation_count: int
    report_issued_at: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class PeerReviewSelection(TypedDict):
    id: str
    peer_review_id: str
    engagement_id: str
    hours_committed: int
    is_scope_limitation: bool
    must_select_category: Optional[str]
    disposition: str
    non_conforming: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict):
    id: str
    peer_review_id: str
    action_code: str
    due_date: str
    evidence_summary: Optional[str]
    evidence_submitted_at: Optional[str]
    rejection_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
