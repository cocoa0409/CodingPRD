"""Entity shapes and enumerations for the AI governance / model approval API.

The TypedDicts are documentation for test authors: they name every field the PRD
declares on a read model. They are declared ``total=False`` because a great many
fields are null until the record reaches the lifecycle stage that populates them.

Two entities — ClassificationSnapshot and GovernanceLedgerEntry — deliberately
carry neither ``updated_at`` nor ``version``. PRD §2.4 states they expose only
``id`` and ``created_at`` alongside their own stamped instant, because an
append-only record is never updated in place.
"""

from typing import Any, Literal, TypedDict

# ─── Role and status vocabularies ──────────────────────────────────────────

Role = Literal[
    "Requester",
    "LegalReviewer",
    "PrivacyReviewer",
    "SecurityReviewer",
    "BusinessReviewer",
    "GovernanceOfficer",
]

UseCaseStatus = Literal[
    "DRAFT",
    "UNDER_REVIEW",
    "CHANGES_REQUESTED",
    "READY_FOR_APPROVAL",
    "APPROVED",
    "UNDER_REASSESSMENT",
    "SUSPENDED",
    "REJECTED",
    "REVOKED",
]

RiskTier = Literal["MINIMAL", "LIMITED", "HIGH", "PROHIBITED"]

DecisionAutonomy = Literal[
    "ADVISORY", "HUMAN_IN_LOOP", "HUMAN_ON_LOOP", "FULLY_AUTOMATED"
]

DataSensitivity = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "SPECIAL_CATEGORY"]

IndividualImpact = Literal["NONE", "LOW", "MATERIAL", "CONSEQUENTIAL"]

Jurisdiction = Literal["EU", "UK", "US_CA", "US_CO", "US_FED"]

GateType = Literal["LEGAL", "PRIVACY", "SECURITY", "BUSINESS"]

ReviewGateStatus = Literal[
    "PENDING", "IN_REVIEW", "CONDITIONS_ISSUED", "CLEARED", "VOIDED"
]

ModelAssetStatus = Literal["REGISTERED", "APPROVED_FOR_USE", "RESTRICTED"]

Hosting = Literal["INTERNAL", "VENDOR_API", "ON_PREM"]

Modality = Literal["TEXT", "VISION", "MULTIMODAL", "TABULAR"]

ModelBindingStatus = Literal["PINNED", "STALE", "RETIRED"]

SupersededReason = Literal[
    "SUPERSEDED_BY_NEW_BINDING",
    "USE_CASE_REVOKED",
    "APPROVAL_SUSPENDED",
    "ASSET_REAPPROVED",
]

AssessmentStatus = Literal["SUBMITTED", "ACCEPTED", "REJECTED", "EXPIRED"]

TermsVariant = Literal["CONSERVATIVE_LEGAL", "DOCUMENTED_TERMS"]

TermsGrade = Literal["A", "B", "C", "D"]

TrainingDataProvenance = Literal[
    "DOCUMENTED_LICENSED", "DOCUMENTED_MIXED", "UNDISCLOSED"
]

OutputRights = Literal[
    "FULL_ASSIGNMENT", "LICENSE_WITH_RESTRICTIONS", "VENDOR_RETAINS"
]

EvalType = Literal["BIAS", "ROBUSTNESS", "HALLUCINATION", "SECURITY_REDTEAM"]

EvaluationStatus = Literal["PLANNED", "PASSED", "FAILED", "VOIDED"]

ReviewMode = Literal["NONE", "SAMPLED", "PRE_DECISION_REVIEW", "DUAL_REVIEW"]

OversightDesignStatus = Literal["DRAFT", "APPROVED", "REJECTED"]

NoticeType = Literal[
    "USER_FACING_AI_DISCLOSURE",
    "AUTOMATED_DECISION_NOTICE",
    "TRAINING_DATA_NOTICE",
    "EMPLOYMENT_SCREENING_NOTICE",
]

NoticeStatus = Literal["PUBLISHED", "WITHDRAWN"]

Severity = Literal["SEV1", "SEV2", "SEV3"]

IncidentCategory = Literal[
    "HARMFUL_OUTPUT", "DRIFT", "PRIVACY_LEAK", "OVERSIGHT_FAILURE"
]

IncidentStatus = Literal["OPEN", "CONTAINED", "ESCALATED", "RESOLVED"]

MonitoringPosture = Literal["HEALTHY", "WATCH", "IMPAIRED"]

ShadowEnvironment = Literal["SANDBOX", "INTERNAL_PILOT", "PRODUCTION"]

DiscoveredSource = Literal[
    "NETWORK_SCAN", "EXPENSE_REPORT", "SELF_REPORT", "VENDOR_INVOICE"
]

ShadowStatus = Literal[
    "DISCOVERED", "LINKED", "GRACE_GRANTED", "RETIRED", "ENFORCED_BLOCK"
]

ClassificationVariant = Literal["INTAKE_PROVISIONAL", "DEPLOYMENT_FINAL"]

ReassessmentStatus = Literal["SCHEDULED", "IN_PROGRESS", "OVERDUE"]

LedgerEntryType = Literal[
    "APPROVAL_GRANTED",
    "APPROVAL_REVOKED",
    "APPROVAL_SUSPENDED",
    "APPROVAL_REINSTATED",
    "GATE_CLEARED",
    "GATE_REOPENED",
    "REASSESSMENT_COMPLETED",
    "BINDING_RETIRED",
    "VENDOR_ASSESSMENT_EXPIRED",
    "SHADOW_ENFORCED",
    "CLASSIFICATION_REJECTED",
    "DISCLOSURE_WITHDRAWN",
]


# ─── Entities ──────────────────────────────────────────────────────────────


class UseCase(TypedDict, total=False):
    """The governed AI use case: intake data plus its whole governance position."""

    id: str
    created_at: str
    updated_at: str
    version: int
    # Declared intake
    title: str
    business_unit: str
    description: str
    affects_individuals: bool
    decision_autonomy: DecisionAutonomy
    data_sensitivity: DataSensitivity
    individual_impact: IndividualImpact
    jurisdictions: list[Jurisdiction]
    deployed_headcount_reach: int
    predecessor_use_case_id: str | None
    requester_user_id: str
    # Lifecycle
    status: UseCaseStatus
    # Provisional classification
    risk_score: int | None
    risk_tier: RiskTier | None
    forced_prohibited: bool
    classification_stale: bool
    classification_cycle_index: int
    pinned_classification_index: int | None
    required_gate_types: list[GateType]
    rejection_reason: str | None
    # Derived counters
    open_conditions_count: int
    cleared_gate_count: int
    passed_eval_count: int
    active_binding_count: int
    safety_flag: bool
    # Approval outcome
    control_credit: int | None
    vendor_penalty: int | None
    final_risk_score: int | None
    final_risk_tier: RiskTier | None
    approved_by_user_id: str | None
    approved_at: str | None
    approval_expires_at: str | None
    # Reassessment schedule
    reassessment_interval_days: int | None
    reassessment_due_at: str | None
    reassessment_cycle_index: int
    reassessment_status: ReassessmentStatus | None
    # Post-deployment
    monitoring_posture: MonitoringPosture | None
    revocation_reason: str | None
    revoked_at: str | None


class ClassificationSnapshot(TypedDict, total=False):
    """Append-only risk scoring record.

    Per PRD §2.4 it carries only ``id`` and ``created_at`` beside its own
    ``computed_at`` — no ``updated_at``, no ``version``.
    """

    id: str
    created_at: str
    computed_at: str
    use_case_id: str
    variant: ClassificationVariant
    cycle_index: int
    impact_points: int
    autonomy_points: int
    sensitivity_points: int
    reach_points: int
    jurisdiction_points: int
    base_score: int
    control_credit: int | None
    vendor_penalty: int | None
    risk_score: int
    risk_tier: RiskTier
    forced_prohibited: bool


class ReviewGate(TypedDict, total=False):
    """One domain reviewer's gate on a use case, and the debt it books."""

    id: str
    created_at: str
    updated_at: str
    version: int
    use_case_id: str
    gate_type: GateType
    status: ReviewGateStatus
    assigned_reviewer_user_id: str | None
    conditions: list[str]
    open_condition_count: int
    control_debt_index: float
    debt_before_clear: float | None
    cleared_by_user_id: str | None
    cleared_at: str | None


class ModelAsset(TypedDict, total=False):
    """A model in the inventory that use cases bind against."""

    id: str
    created_at: str
    updated_at: str
    version: int
    provider: str
    model_name: str
    model_version: str
    hosting: Hosting
    modality: Modality
    is_third_party: bool
    status: ModelAssetStatus
    vendor_terms_grade: TermsGrade | None
    active_binding_count: int
    enforced_shadow_count: int


class ModelBinding(TypedDict, total=False):
    """A use case's pin of one asset at one asset version."""

    id: str
    created_at: str
    updated_at: str
    version: int
    use_case_id: str
    model_asset_id: str
    pinned_model_version: int
    status: ModelBindingStatus
    superseded_reason: SupersededReason | None
    pinned_at: str
    retired_at: str | None


class VendorModelAssessment(TypedDict, total=False):
    """Third-party terms review, graded on submission and again on decision."""

    id: str
    created_at: str
    updated_at: str
    version: int
    model_asset_id: str
    vendor_name: str
    training_data_provenance: TrainingDataProvenance
    output_rights: OutputRights
    retention_days: int | None
    retention_opt_out: bool
    subprocessors_disclosed: bool
    status: AssessmentStatus
    terms_variant: TermsVariant
    effective_retention_days: int
    terms_risk_points: int
    terms_grade: TermsGrade
    decided_by_user_id: str | None
    decided_at: str | None
    decision_note: str | None


class TestEvaluation(TypedDict, total=False):
    """A scheduled model test run holding an exclusive window on its asset."""

    id: str
    created_at: str
    updated_at: str
    version: int
    use_case_id: str
    model_binding_id: str
    eval_type: EvalType
    status: EvaluationStatus
    pinned_risk_tier: RiskTier
    required_metric_name: str
    required_metric_threshold: float
    required_sample_size: int
    window_start_at: str
    window_end_at: str
    observed_metric_value: float | None
    sample_size: int | None
    evidence_uri: str | None
    completed_at: str | None


class OversightDesign(TypedDict, total=False):
    """The human-oversight arrangement, scored for adequacy on filing."""

    id: str
    created_at: str
    updated_at: str
    version: int
    use_case_id: str
    review_mode: ReviewMode
    sample_pct: int
    escalation_sla_hours: int
    reviewer_role: Role
    override_capability: bool
    status: OversightDesignStatus
    adequacy_score: int
    required_adequacy_score: int
    decided_by_user_id: str | None
    decided_at: str | None
    decision_rationale: str | None


class DisclosureNotice(TypedDict, total=False):
    """A statutory notice published over a closed window in one jurisdiction."""

    id: str
    created_at: str
    updated_at: str
    version: int
    use_case_id: str
    notice_type: NoticeType
    jurisdiction: Jurisdiction
    effective_from: str
    effective_to: str
    locale_count: int
    status: NoticeStatus
    withdrawn_at: str | None


class MonitoringIncident(TypedDict, total=False):
    """A post-deployment incident with a derived containment deadline."""

    id: str
    created_at: str
    updated_at: str
    version: int
    use_case_id: str
    severity: Severity
    category: IncidentCategory
    summary: str
    detected_at: str
    containment_hours: int
    containment_deadline_at: str
    status: IncidentStatus
    reported_to_regulator: bool
    contained_at: str | None
    resolved_at: str | None


class ShadowDeployment(TypedDict, total=False):
    """An unapproved deployment found in the estate, on a grace clock."""

    id: str
    created_at: str
    updated_at: str
    version: int
    model_asset_id: str
    claimed_use_case_id: str | None
    environment: ShadowEnvironment
    discovered_source: DiscoveredSource
    discovered_at: str
    grace_days_granted: int
    grace_deadline_at: str
    status: ShadowStatus


class GovernanceLedgerEntry(TypedDict, total=False):
    """Append-only conservation record.

    Per PRD §2.4 it carries only ``id`` and ``created_at`` beside its own
    ``recorded_at`` — no ``updated_at``, no ``version``.
    """

    id: str
    created_at: str
    recorded_at: str
    use_case_id: str
    entry_type: LedgerEntryType
    reach_delta: int
    debt_delta: float
    actor_user_id: str
    note: str | None


class InventorySummary(TypedDict, total=False):
    """The reconciliation read over the whole governance inventory."""

    inventory_count: int
    portfolio_approved_reach: int
    portfolio_approved_reach_high_tier: int
    control_debt_index_total: float
    ledger_reach_balance: int
    ledger_debt_balance: float
    open_incident_count: int
    unapproved_shadow_count: int


class SweepResult(TypedDict, total=False):
    """The counters the periodic governance sweep returns."""

    reassessments_opened: int
    approvals_suspended: int
    shadows_enforced: int
    assets_restricted: int
    assessments_expired: int


JsonDict = dict[str, Any]
