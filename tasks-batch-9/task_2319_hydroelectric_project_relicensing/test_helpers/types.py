"""Domain types for the Hydroelectric Project Relicensing API.

Entity TypedDicts, lifecycle enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    LICENSEE = "Licensee"
    AGENCY_REVIEWER = "AgencyReviewer"
    STAKEHOLDER = "Stakeholder"
    STATE_CERTIFIER = "StateCertifier"
    REGULATOR = "Regulator"


# ---------------------------------------------------------------------------
# Lifecycle / enumerated values
# ---------------------------------------------------------------------------
class ProjectStage(str, Enum):
    PRE_FILING = "PRE_FILING"
    PAD_FILED = "PAD_FILED"
    STUDY_PHASE = "STUDY_PHASE"
    APPLICATION_FILED = "APPLICATION_FILED"
    UNDER_ENVIRONMENTAL_REVIEW = "UNDER_ENVIRONMENTAL_REVIEW"
    LICENSED = "LICENSED"


class TimelinePosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    DELINQUENT = "DELINQUENT"


class RegulatoryPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ProjectWqcStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    CERTIFIED_WITH_CONDITIONS = "CERTIFIED_WITH_CONDITIONS"
    DENIED = "DENIED"
    WAIVED = "WAIVED"


class HazardClass(str, Enum):
    HIGH = "HIGH"
    SIGNIFICANT = "SIGNIFICANT"
    LOW = "LOW"


class CulturalSensitivity(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class StudyPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_AGENCY_REVIEW = "UNDER_AGENCY_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ResourceCategory(str, Enum):
    FISH_PASSAGE = "FISH_PASSAGE"
    WATER_QUALITY = "WATER_QUALITY"
    RECREATION = "RECREATION"
    CULTURAL = "CULTURAL"


class FieldworkStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class StudyReviewStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    ADDITIONAL_REQUIRED = "ADDITIONAL_REQUIRED"


class CommentResolutionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class CommentDisposition(str, Enum):
    ADOPTED = "ADOPTED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class PartyType(str, Enum):
    AGENCY = "AGENCY"
    TRIBE = "TRIBE"
    NGO = "NGO"


class SettlementStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    CIRCULATED = "CIRCULATED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class SignaturePosition(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    ABSTAIN = "ABSTAIN"


class WqcStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CERTIFIED_WITH_CONDITIONS = "CERTIFIED_WITH_CONDITIONS"
    DENIED = "DENIED"
    WAIVED = "WAIVED"


class MeasureSource(str, Enum):
    SETTLEMENT = "SETTLEMENT"
    WQC_CONDITION = "WQC_CONDITION"
    AGENCY_PRESCRIPTION = "AGENCY_PRESCRIPTION"
    LICENSEE_PROPOSED = "LICENSEE_PROPOSED"


class MeasureStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INCLUDED = "INCLUDED"
    IMPLEMENTED = "IMPLEMENTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class CostEstimateVariant(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    DEFINITIVE = "DEFINITIVE"


class ApplicationType(str, Enum):
    ORIGINAL_RELICENSE = "ORIGINAL_RELICENSE"
    AMENDMENT = "AMENDMENT"


class FilingStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    SUSPENDED = "SUSPENDED"
    LICENSED = "LICENSED"
    SUPERSEDED = "SUPERSEDED"


class EaStage(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SCOPING = "SCOPING"
    DRAFT_EA = "DRAFT_EA"
    FINAL_EA = "FINAL_EA"


class ComplianceState(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    COMPLIANCE_FLAGGED = "COMPLIANCE_FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class ReportBasis(str, Enum):
    CALENDAR = "CALENDAR"
    LICENSE_ANNIVERSARY = "LICENSE_ANNIVERSARY"


class ObligationType(str, Enum):
    PME_IMPLEMENTATION = "PME_IMPLEMENTATION"
    DAM_SAFETY_INSPECTION = "DAM_SAFETY_INSPECTION"
    PUBLIC_SAFETY_SIGNAGE = "PUBLIC_SAFETY_SIGNAGE"
    EAP_EXERCISE = "EAP_EXERCISE"


class ObligationStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    CERTIFIED = "CERTIFIED"
    WAIVED = "WAIVED"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class RelicensingProject(TypedDict):
    id: str
    license_number: str
    project_name: str
    installed_capacity_mw: float
    base_annual_generation_mwh: float
    license_expiration_date: str
    infeasibility_waiver_granted: bool
    stage: str
    pad_filed_at: Optional[str]
    pad_year: Optional[int]
    application_filed_at: Optional[str]
    timeline_posture: str
    regulatory_posture: str
    total_pme_annual_cost_usd: float
    total_generation_loss_mwh: float
    administrative_annual_charge_usd: float
    total_annual_burden_usd: float
    burden_ratio_pct: float
    economically_infeasible: bool
    wqc_status: str
    unresolved_mandatory_comment_count: int
    open_deficiency_count: int
    compliance_flag_count: int
    last_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dam(TypedDict):
    id: str
    project_id: str
    dam_code: str
    hazard_class: str
    inspection_interval_months: int
    eap_exercise_required: bool
    max_concurrent_field_activities: int
    created_at: str
    updated_at: str
    version: int


class StudySite(TypedDict):
    id: str
    project_id: str
    site_code: str
    river_mile: float
    min_rest_buffer_days: int
    cultural_sensitivity: str
    created_at: str
    updated_at: str
    version: int


class StudyPlan(TypedDict):
    id: str
    project_id: str
    plan_title: str
    status: str
    revision_round: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    open_comment_count: int
    unresolved_mandatory_comment_count: int
    attached_study_count: int
    created_at: str
    updated_at: str
    version: int


class ResourceStudy(TypedDict):
    id: str
    study_plan_id: str
    site_id: str
    resource_category: str
    study_title: str
    fieldwork_window_start: str
    fieldwork_window_end: str
    cultural_clearance_reference: Optional[str]
    fieldwork_status: str
    review_status: str
    additional_round_count: int
    report_submitted_at: Optional[str]
    report_submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementParty(TypedDict):
    id: str
    project_id: str
    party_name: str
    party_type: str
    has_conditioning_authority: bool
    vote_weight: int
    contact_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    project_id: str
    title: str
    status: str
    round_number: int
    circulated_at: Optional[str]
    executed_at: Optional[str]
    withdrawn_at: Optional[str]
    support_pct: Optional[float]
    total_vote_weight: Optional[int]
    included_measure_count: int
    created_at: str
    updated_at: str
    version: int


class WaterQualityCertification(TypedDict):
    id: str
    project_id: str
    certifying_agency_name: str
    status: str
    requested_at: str
    statutory_waiver_date: str
    decided_at: Optional[str]
    condition_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PmeMeasure(TypedDict):
    id: str
    project_id: str
    settlement_id: Optional[str]
    prerequisite_measure_id: Optional[str]
    measure_name: str
    resource_category: str
    source: str
    status: str
    capital_cost_usd: float
    annual_om_cost_usd: float
    construction_start_year: int
    implementation_months: int
    flow_release_cfs: float
    gross_head_ft: float
    release_days: int
    cost_estimate_variant: str
    escalated_capital_usd: float
    annualized_capital_usd: float
    annual_cost_usd: float
    annual_generation_loss_mwh: float
    annual_generation_value_usd: float
    annual_burden_usd: float
    created_by_user_id: str
    definitive_estimate_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseApplication(TypedDict):
    id: str
    project_id: str
    amends_order_id: Optional[str]
    application_type: str
    filing_status: str
    ea_stage: str
    filed_at: str
    pinned_study_plan_id: Optional[str]
    pinned_study_plan_version: Optional[int]
    pinned_settlement_id: Optional[str]
    pinned_settlement_version: Optional[int]
    pinned_measure_ids: List[str]
    pinned_total_annual_burden_usd: float
    deficiency_count: int
    last_deficiency_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseOrder(TypedDict):
    id: str
    application_id: str
    order_number: str
    effective_date: str
    compliance_state: str
    amendment_pending: bool
    article_count: int
    open_violation_count: int
    last_report_basis: Optional[str]
    last_report_period_year: Optional[int]
    assessed_obligation_count: int
    noncompliant_obligation_count: int
    compliance_score: float
    last_report_filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceObligation(TypedDict):
    id: str
    order_id: str
    pme_measure_id: Optional[str]
    dam_id: Optional[str]
    obligation_type: str
    due_date: str
    status: str
    activity_window_start: Optional[str]
    activity_window_end: Optional[str]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    overdue_marked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records: id + created_at only (no updated_at, no version)
# ---------------------------------------------------------------------------
class ConsultationComment(TypedDict):
    id: str
    study_plan_id: str
    party_id: str
    resource_category: str
    comment_text: str
    is_mandatory_condition: bool
    resolution_status: str
    disposition: Optional[str]
    resolved_at: Optional[str]
    reopen_count: int
    created_at: str


class SettlementSignature(TypedDict):
    id: str
    settlement_id: str
    party_id: str
    round_number: int
    position: str
    share_pct: Optional[float]
    signed_at: str
    created_at: str
