"""Domain types for the Federal Environmental Review API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    POLICY_ADMIN = "PolicyAdmin"
    NEPA_COORDINATOR = "NepaCoordinator"
    RESOURCE_SPECIALIST = "ResourceSpecialist"
    REVIEWING_OFFICIAL = "ReviewingOfficial"
    AGENCY_LIAISON = "AgencyLiaison"
    DECIDING_OFFICIAL = "DecidingOfficial"
    OBJECTION_REVIEWING_OFFICER = "ObjectionReviewingOfficer"
    PUBLIC_COMMENTER = "PublicCommenter"


# --------------------------------------------------------------------------
# Status / enumerated value sets
# --------------------------------------------------------------------------

class ReviewStage(str, Enum):
    INTAKE = "INTAKE"
    SCREENED = "SCREENED"
    CLASSIFIED = "CLASSIFIED"
    SCOPING = "SCOPING"
    ANALYSIS = "ANALYSIS"
    DRAFT_PUBLISHED = "DRAFT_PUBLISHED"
    COMMENT_CLOSED = "COMMENT_CLOSED"
    DECIDED = "DECIDED"
    RECORD_CERTIFIED = "RECORD_CERTIFIED"


class ActionClassification(str, Enum):
    CATEGORICAL_EXCLUSION = "CATEGORICAL_EXCLUSION"
    ENVIRONMENTAL_ASSESSMENT = "ENVIRONMENTAL_ASSESSMENT"
    ENVIRONMENTAL_IMPACT_STATEMENT = "ENVIRONMENTAL_IMPACT_STATEMENT"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgencyRole(str, Enum):
    COOPERATING = "COOPERATING"
    CONSULTING = "CONSULTING"
    BOTH = "BOTH"


class EcScreenStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    CLEARED = "CLEARED"
    TRIGGERED = "TRIGGERED"


class EcScreenDisposition(str, Enum):
    RETURNED = "RETURNED"
    CLEARED = "CLEARED"
    TRIGGERED = "TRIGGERED"


class ExtraordinaryCircumstanceCode(str, Enum):
    EC_HISTORIC = "EC_HISTORIC"
    EC_ENDANGERED_SPECIES = "EC_ENDANGERED_SPECIES"
    EC_WETLAND = "EC_WETLAND"
    EC_ENVIRONMENTAL_JUSTICE = "EC_ENVIRONMENTAL_JUSTICE"
    EC_FLOODPLAIN = "EC_FLOODPLAIN"


class PurposeNeedStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class ScopingKind(str, Enum):
    PUBLIC = "PUBLIC"
    AGENCY = "AGENCY"


class ScopingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ResourceArea(str, Enum):
    BIOLOGICAL = "BIOLOGICAL"
    CULTURAL = "CULTURAL"
    AIR = "AIR"
    WATER = "WATER"
    SOCIOECONOMIC = "SOCIOECONOMIC"


class IssueOrigin(str, Enum):
    PUBLIC = "PUBLIC"
    AGENCY = "AGENCY"


class IssueSignificance(str, Enum):
    SIGNIFICANT = "SIGNIFICANT"
    NON_SIGNIFICANT = "NON_SIGNIFICANT"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    ANALYZED = "ANALYZED"
    WITHDRAWN = "WITHDRAWN"


class AlternativeKind(str, Enum):
    NO_ACTION = "NO_ACTION"
    PROPOSED_ACTION = "PROPOSED_ACTION"
    REASONABLE_RANGE = "REASONABLE_RANGE"


class ScreeningStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SCREENED_IN = "SCREENED_IN"
    SCREENED_OUT = "SCREENED_OUT"
    STALE = "STALE"


class TemporalScope(str, Enum):
    PAST = "PAST"
    PRESENT = "PRESENT"
    REASONABLY_FORESEEABLE = "REASONABLY_FORESEEABLE"


class InclusionStatus(str, Enum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class ResourceAnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


class SignificanceBasis(str, Enum):
    UNMITIGATED = "UNMITIGATED"
    MITIGATED = "MITIGATED"


class SignificanceDetermination(str, Enum):
    SIGNIFICANT = "SIGNIFICANT"
    NOT_SIGNIFICANT = "NOT_SIGNIFICANT"


class ConsultationType(str, Enum):
    ESA_SECTION_7 = "ESA_SECTION_7"
    NHPA_SECTION_106 = "NHPA_SECTION_106"
    CWA_SECTION_404 = "CWA_SECTION_404"
    COOPERATING_AGENCY = "COOPERATING_AGENCY"


class ConsultationStatus(str, Enum):
    PENDING = "PENDING"
    CONCURRED = "CONCURRED"
    CONDITIONAL_CONCURRENCE = "CONDITIONAL_CONCURRENCE"
    NOT_CONCURRED = "NOT_CONCURRED"
    WITHDRAWN = "WITHDRAWN"


class DocumentType(str, Enum):
    CE_MEMORANDUM = "CE_MEMORANDUM"
    ENVIRONMENTAL_ASSESSMENT = "ENVIRONMENTAL_ASSESSMENT"
    ENVIRONMENTAL_IMPACT_STATEMENT = "ENVIRONMENTAL_IMPACT_STATEMENT"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class CommentStatus(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CommentDisposition(str, Enum):
    RECEIVED = "RECEIVED"
    RESPONDED = "RESPONDED"
    DUPLICATE = "DUPLICATE"


class ResponseCategory(str, Enum):
    FACTUAL_CORRECTION = "FACTUAL_CORRECTION"
    ANALYSIS_REVISED = "ANALYSIS_REVISED"
    NO_CHANGE_NEEDED = "NO_CHANGE_NEEDED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class DecisionType(str, Enum):
    CE_DETERMINATION = "CE_DETERMINATION"
    FONSI = "FONSI"
    MITIGATED_FONSI = "MITIGATED_FONSI"
    RECORD_OF_DECISION = "RECORD_OF_DECISION"


class DecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    VACATED = "VACATED"


class CommitmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    BINDING = "BINDING"
    RELEASED = "RELEASED"


class MonitoringStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"


class ObjectorType(str, Enum):
    COMMENTER = "COMMENTER"
    AGENCY = "AGENCY"
    TRIBE = "TRIBE"
    OTHER = "OTHER"


class StandingBasis(str, Enum):
    SUBSTANTIVE_COMMENT = "SUBSTANTIVE_COMMENT"
    AGENCY_CONSULTATION = "AGENCY_CONSULTATION"
    NONE = "NONE"


class ObjectionStatus(str, Enum):
    FILED = "FILED"
    DENIED = "DENIED"
    REMANDED = "REMANDED"


class ObjectionDisposition(str, Enum):
    DENIED = "DENIED"
    REMANDED = "REMANDED"


class RecordEntryCode(str, Enum):
    EC_SCREEN_ADJUDICATED = "EC_SCREEN_ADJUDICATED"
    CLASSIFICATION_ASSIGNED = "CLASSIFICATION_ASSIGNED"
    CLASSIFICATION_ESCALATED = "CLASSIFICATION_ESCALATED"
    PN_ADOPTED = "PN_ADOPTED"
    SCOPING_CLOSED = "SCOPING_CLOSED"
    ANALYSIS_FINALIZED = "ANALYSIS_FINALIZED"
    ANALYSIS_REOPENED = "ANALYSIS_REOPENED"
    DOCUMENT_PUBLISHED = "DOCUMENT_PUBLISHED"
    DOCUMENT_SUPERSEDED = "DOCUMENT_SUPERSEDED"
    COMMENT_PERIOD_CLOSED = "COMMENT_PERIOD_CLOSED"
    DOCUMENT_FINALIZED = "DOCUMENT_FINALIZED"
    DECISION_SIGNED = "DECISION_SIGNED"
    DECISION_VACATED = "DECISION_VACATED"
    OBJECTION_FILED = "OBJECTION_FILED"
    OBJECTION_RESOLVED = "OBJECTION_RESOLVED"
    RECORD_CERTIFIED = "RECORD_CERTIFIED"


class RelatedEntityType(str, Enum):
    EXTRAORDINARY_CIRCUMSTANCE_SCREEN = "ExtraordinaryCircumstanceScreen"
    PURPOSE_NEED_STATEMENT = "PurposeNeedStatement"
    SCOPING_PERIOD = "ScopingPeriod"
    RESOURCE_ANALYSIS = "ResourceAnalysis"
    NEPA_DOCUMENT = "NepaDocument"
    DECISION_DOCUMENT = "DecisionDocument"
    OBJECTION = "Objection"
    PROPOSED_ACTION = "ProposedAction"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------

class ReviewOffice(TypedDict):
    id: str
    office_code: str
    name: str
    ce_threshold_disturbance_hectares: float
    ea_threshold_disturbance_hectares: float
    min_scoping_days: int
    min_ea_comment_days: int
    min_eis_comment_days: int
    objection_window_days: int
    cumulative_radius_km: float
    significance_threshold: float
    intensity_weight: float
    context_weight: float
    min_alternative_feasibility: float
    max_mitigated_reduction_points: float
    cost_per_reduction_point_cents: int
    monitoring_escalation_factor: float
    max_binding_obligation_cents: int
    extraordinary_circumstance_codes: List[str]
    ec_severity_trigger_threshold: int
    min_screened_in_alternatives_ea: int
    min_screened_in_alternatives_eis: int
    binding_obligation_cents: int
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict):
    id: str
    agency_code: str
    name: str
    agency_role: str
    max_concurrent_consultations: int
    handoff_buffer_days: int
    statutory_response_days: int
    status: str
    active_consultation_count: int
    created_at: str
    updated_at: str
    version: int


class ProposedAction(TypedDict):
    id: str
    office_id: str
    title: str
    disturbance_hectares: float
    reference_cost_cents: int
    in_critical_habitat: bool
    affects_historic_property: bool
    tribal_interest: bool
    floodplain_or_wetland: bool
    review_stage: str
    classification: Optional[str]
    ec_screen_outcome: Optional[str]
    extraordinary_circumstance_flag: bool
    significant_issue_count: int
    unaddressed_issue_count: int
    alternatives_screened_in_count: int
    finalized_analysis_count: int
    max_unmitigated_score: float
    cumulative_intensity_index: float
    record_entry_count: int
    record_certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtraordinaryCircumstanceScreen(TypedDict):
    id: str
    action_id: str
    findings: List[dict]
    triggered_codes: List[str]
    max_severity: int
    screen_round: int
    status: str
    adjudicator_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurposeNeedStatement(TypedDict):
    id: str
    action_id: str
    purpose_text: str
    need_text: str
    goal_codes: List[str]
    constraint_codes: List[str]
    version_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScopingPeriod(TypedDict):
    id: str
    action_id: str
    scoping_kind: str
    start_at: str
    end_at: str
    duration_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Issue(TypedDict):
    id: str
    action_id: str
    scoping_period_id: str
    resource_area: str
    origin: str
    significance: str
    summary: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Alternative(TypedDict):
    id: str
    action_id: str
    label: str
    alternative_kind: str
    goal_alignment_codes: List[str]
    estimated_cost_cents: int
    pinned_pn_statement_id: str
    feasibility_score: float
    screening_status: str
    created_at: str
    updated_at: str
    version: int


class CumulativeAction(TypedDict):
    id: str
    action_id: str
    resource_area: str
    label: str
    intensity_contribution: float
    footprint_hectares: float
    distance_km: float
    temporal_scope: str
    inclusion_status: str
    created_at: str
    updated_at: str
    version: int


class ResourceAnalysis(TypedDict):
    id: str
    action_id: str
    resource_area: str
    intensity_score: float
    context_sensitivity_score: float
    affected_area_hectares: float
    mitigation_reduction_points: float
    cumulative_effect_score: float
    unmitigated_score: float
    mitigated_score: float
    significance_score: Optional[float]
    significance_determination: Optional[str]
    variant_applied: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsultationRequest(TypedDict):
    id: str
    action_id: str
    agency_id: str
    consultation_type: str
    requested_start_at: str
    statutory_due_at: str
    is_required: bool
    status: str
    responded_at: Optional[str]
    conditions_text: Optional[str]
    late: bool
    created_at: str
    updated_at: str
    version: int


class NepaDocument(TypedDict):
    id: str
    action_id: str
    document_type: str
    title: str
    publication_status: str
    comment_status: str
    comment_period_start_at: Optional[str]
    comment_period_end_at: Optional[str]
    comment_period_days: int
    substantive_comment_count: int
    responded_substantive_count: int
    unresolved_substantive_count: int
    response_completeness_pct: float
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    document_id: str
    assigned_issue_id: Optional[str]
    commenter_name: str
    resource_area: str
    is_substantive: bool
    body: str
    disposition: str
    response_text: Optional[str]
    response_category: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DecisionDocument(TypedDict):
    id: str
    action_id: str
    selected_alternative_id: str
    decision_type: str
    prepared_by_user_id: str
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    status: str
    committed_obligation_cents: int
    base_obligation_cents: int
    credit_points: float
    contingency_fee_cents: int
    binding_obligation_cents: int
    mitigated_max_score: float
    objection_window_opens_at: Optional[str]
    objection_window_closes_at: Optional[str]
    objection_count: int
    created_at: str
    updated_at: str
    version: int


class MitigationCommitment(TypedDict):
    id: str
    decision_id: str
    source_analysis_id: str
    measure_text: str
    cost_estimate_cents: int
    monitoring_years: int
    annual_monitoring_cost_cents: int
    reduction_points: float
    lifecycle_obligation_cents: int
    status: str
    monitoring_status: str
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict):
    id: str
    decision_id: str
    objector_name: str
    objector_type: str
    basis_issue_area: str
    standing_basis: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdminRecordEntry(TypedDict):
    """Administrative record entries are immutable by construction, so an entry
    carries only ``id`` and ``created_at`` — it has neither ``updated_at`` nor
    ``version`` (PRD 2.4)."""
    id: str
    action_id: str
    sequence_no: int
    entry_code: str
    occurred_at: str
    actor_role: str
    actor_user_id: Optional[str]
    summary: str
    related_entity_type: str
    related_entity_ref: str
    created_at: str
