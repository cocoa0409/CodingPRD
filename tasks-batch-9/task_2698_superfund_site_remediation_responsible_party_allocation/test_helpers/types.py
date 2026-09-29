"""Typed shapes for the fourteen resources the PRD describes.

These are documentation-grade `TypedDict`s: they name every field the PRD says
a response body carries, so a test that reads a field name can be checked
against this module rather than against a guess. Nothing here is enforced at
runtime; the runtime shape checks live in `assertions.py`.
"""
from typing import List, Literal, Optional, TypedDict

Role = Literal[
    "RemedialProjectManager",
    "AllocationFacilitator",
    "SettlementCounsel",
    "PRPRepresentative",
    "Contractor",
    "CommunityMember",
]

ListingStatus = Literal[
    "PROPOSED",
    "LISTED",
    "RI_FS_UNDERWAY",
    "ROD_SIGNED",
    "CONSTRUCTION",
    "OM_PHASE",
    "REMEDY_REEVALUATION",
    "DELETED_FROM_NPL",
]
CostPosture = Literal["OPEN", "RESTRICTED", "FROZEN"]
PartyType = Literal["OWNER_OPERATOR", "GENERATOR", "TRANSPORTER", "ARRANGER"]
PrpStatus = Literal[
    "IDENTIFIED",
    "NOTIFIED",
    "PARTICIPATING",
    "RECALCITRANT",
    "ORPHAN",
    "SETTLED",
    "DE_MINIMIS_SETTLED",
]
AcquisitionType = Literal["PURCHASE", "MERGER", "FORECLOSURE", "LEASE"]
ToxicityClass = Literal["I", "II", "III", "IV"]
EvidenceGrade = Literal["A", "B", "C"]
WasteInStatus = Literal["SUBMITTED", "VERIFIED", "REJECTED"]
ExposureMedium = Literal["SOIL", "GROUNDWATER", "AIR", "SEDIMENT"]
QaStatus = Literal["VALID", "ESTIMATED", "REJECTED"]
RifsStatus = Literal["DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED"]
RodStatus = Literal[
    "DRAFT", "PUBLIC_COMMENT", "SIGNED", "AMENDMENT_REQUIRED", "WITHDRAWN"
]
RoundStatus = Literal["DRAFTING", "BALLOTING", "ADOPTED", "FAILED", "SUPERSEDED"]
ShareDisposition = Literal["PENDING", "ALLOCATED", "ORPHANED", "SETTLED"]
Ballot = Literal["ACCEPT", "REJECT", "ABSTAIN"]
DecreeScopeType = Literal["RIFS_AOC", "RD_RA_CONSENT_DECREE"]
DecreeLegalStatus = Literal["NEGOTIATING", "LODGED", "ENTERED", "TERMINATED"]
DecreeComplianceStatus = Literal["COMPLIANT", "IN_VIOLATION", "PENALTY_ACCRUING"]
ComplianceEventType = Literal["VIOLATION", "PENALTY_ASSESSMENT", "CURE"]
ContractStatus = Literal[
    "SOLICITATION", "AWARDED", "CONSTRUCTION_COMPLETE", "CLOSED"
]
ActivityType = Literal[
    "CONSTRUCTION", "LONG_TERM_MONITORING", "MAINTENANCE_SHUTDOWN"
]
ProtectivenessDetermination = Literal[
    "PROTECTIVE", "PROTECTIVE_SHORT_TERM", "NOT_PROTECTIVE"
]
ActionType = Literal[
    "DE_MINIMIS_SETTLEMENT", "COST_RECOVERY_DEMAND", "CONTRIBUTION_CLAIM"
]
ActionStatus = Literal[
    "OFFERED", "ACCEPTED", "REJECTED", "COLLECTED", "VOIDED", "SUPERSEDED"
]


class Site(TypedDict, total=False):
    id: str
    name: str
    epa_region: int
    hrs_score: float
    listing_status: ListingStatus
    listing_reference: Optional[str]
    cost_posture: CostPosture
    verified_waste_volume_tons: float
    oversight_direct_cents: int
    oversight_indirect_rate_bp: int
    oversight_indirect_cents: int
    oversight_billed_cents: int
    oversight_cap_utilization_pct: Optional[float]
    total_response_cost_cents: int
    recovered_cost_cents: int
    orphan_write_off_cents: int
    unrecovered_cost_cents: int
    adopted_round_id: Optional[str]
    construction_complete_at: Optional[str]
    five_year_review_due_at: Optional[str]
    last_five_year_review_at: Optional[str]
    last_protectiveness_determination: Optional[ProtectivenessDetermination]
    created_at: str
    updated_at: str
    version: int


class PotentiallyResponsibleParty(TypedDict, total=False):
    id: str
    site_id: str
    legal_name: str
    party_type: PartyType
    viability_score: int
    status: PrpStatus
    notice_reference: Optional[str]
    submitted_volume_tons: float
    verified_volume_tons: float
    effective_volume_tons: float
    max_toxicity_class: Optional[ToxicityClass]
    ownership_days_total: int
    volumetric_share_pct: float
    de_minimis_eligible: bool
    contribution_protection: bool
    defunct_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OwnershipPeriod(TypedDict, total=False):
    """Immutable: carries only `id` and `created_at` beyond its own fields."""

    id: str
    site_id: str
    prp_id: str
    start_date: str
    end_date: Optional[str]
    acquisition_type: AcquisitionType
    ownership_days: int
    created_at: str


class WasteInRecord(TypedDict, total=False):
    id: str
    site_id: str
    prp_id: str
    volume_tons: float
    toxicity_class: ToxicityClass
    evidence_grade: EvidenceGrade
    disposal_year: int
    transporter_name: Optional[str]
    status: WasteInStatus
    verified_volume_tons: Optional[float]
    effective_volume_tons: float
    verification_note: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContaminantSample(TypedDict, total=False):
    """Immutable: carries only `id` and `created_at` beyond its own fields."""

    id: str
    remedial_investigation_id: str
    medium: ExposureMedium
    contaminant: str
    concentration_ug_per_l: float
    qa_status: QaStatus
    collected_at: str
    lab_reference: str
    created_at: str


class RemedialInvestigation(TypedDict, total=False):
    id: str
    site_id: str
    scope_summary: str
    exposure_medium: ExposureMedium
    status: RifsStatus
    authored_by_user_id: str
    approved_by_user_id: Optional[str]
    revision_round_count: int
    valid_sample_count: int
    central_tendency_epc_ug_per_l: Optional[float]
    rme_epc_ug_per_l: Optional[float]
    central_tendency_risk: Optional[float]
    rme_risk: Optional[float]
    hazard_index: Optional[float]
    action_level_exceeded: bool
    created_at: str
    updated_at: str
    version: int


class RemedyAlternative(TypedDict, total=False):
    id: str
    remedial_investigation_id: str
    label: str
    capital_cost_cents: int
    annual_om_cost_cents: int
    om_years: int
    discount_rate_bp: int
    effectiveness_score: int
    implementability_score: int
    npv_cents: int
    cost_score: float
    remedy_score: float
    selected_by_rod_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecordOfDecision(TypedDict, total=False):
    id: str
    site_id: str
    remedial_investigation_id: str
    proposed_plan_summary: str
    comment_period_days: int
    status: RodStatus
    comment_period_start: Optional[str]
    comment_period_end: Optional[str]
    public_comments_count: int
    responsiveness_summary: Optional[str]
    selected_alternative_id: Optional[str]
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationRound(TypedDict, total=False):
    id: str
    site_id: str
    round_number: int
    status: RoundStatus
    facilitator_user_id: str
    weight_volume_bp: int
    weight_toxicity_bp: int
    weight_ownership_bp: int
    share_count: int
    balloted_count: int
    accept_share_pct: float
    allocated_share_total_pct: float
    orphan_share_pct: float
    settled_share_pct: float
    revision_note: Optional[str]
    adopted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationShare(TypedDict, total=False):
    id: str
    allocation_round_id: str
    prp_id: str
    provisional_pct: float
    final_pct: Optional[float]
    pre_settlement_final_pct: Optional[float]
    disposition: ShareDisposition
    ballot: Optional[Ballot]
    ballot_rationale: Optional[str]
    ballot_cast_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentDecree(TypedDict, total=False):
    id: str
    site_id: str
    scope_type: DecreeScopeType
    scope_summary: str
    party_prp_ids: List[str]
    oversight_cost_cap_cents: int
    stipulated_penalty_per_day_cents: int
    performance_deadline: str
    legal_status: DecreeLegalStatus
    compliance_status: DecreeComplianceStatus
    lodged_at: Optional[str]
    public_comment_close_at: Optional[str]
    court_docket_number: Optional[str]
    entered_at: Optional[str]
    terminated_at: Optional[str]
    first_noncompliance_date: Optional[str]
    last_assessment_at: Optional[str]
    violation_type: Optional[str]
    open_violation_count: int
    days_in_violation: int
    penalty_cap_cents: int
    accrued_penalty_cents: int
    paid_penalty_cents: int
    penalty_capped: bool
    created_at: str
    updated_at: str
    version: int


class RemediationContract(TypedDict, total=False):
    id: str
    site_id: str
    record_of_decision_id: str
    solicitation_reference: str
    engineer_estimate_cents: int
    status: ContractStatus
    contractor_name: Optional[str]
    awarded_amount_cents: Optional[int]
    awarded_at: Optional[str]
    max_concurrent_windows: int
    work_window_count: int
    completion_date: Optional[str]
    punch_list_items: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WorkWindow(TypedDict, total=False):
    """Immutable: carries only `id` and `created_at` beyond its own fields."""

    id: str
    remediation_contract_id: str
    activity_type: ActivityType
    start_at: str
    end_at: str
    buffered_start_at: str
    buffered_end_at: str
    crew_size: int
    description: Optional[str]
    created_at: str


class CostRecoveryAction(TypedDict, total=False):
    id: str
    site_id: str
    respondent_prp_id: str
    claimant_prp_id: Optional[str]
    action_type: ActionType
    demanded_cents: int
    received_cents: int
    status: ActionStatus
    respondent_share_pct_at_offer: float
    premium_floor_cents: Optional[int]
    response_note: Optional[str]
    receipt_reference: Optional[str]
    received_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostLedger(TypedDict, total=False):
    total_response_cost_cents: int
    recovered_cost_cents: int
    orphan_write_off_cents: int
    unrecovered_cost_cents: int
    oversight_direct_cents: int
    oversight_indirect_rate_bp: int
    oversight_indirect_cents: int
    oversight_billed_cents: int
    oversight_cap_utilization_pct: Optional[float]
    allocated_share_total_pct: float
    orphan_share_pct: float
    settled_share_pct: float
    ledger_balanced: bool
