"""
TypedDict shapes for the fourteen resource types of the Bridge Inspection &
Load Rating Program API.

Field names and optionality are transcribed from PRD §2.5 (the common
system-managed field set) and from the resource descriptions in PRD §3.1 – §3.9.
These shapes are documentation-as-code: they let a reader see, without leaving
the test suite, exactly which keys a response body is expected to carry.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─── PRD §2.5: the system-managed field set carried by thirteen of the ──────
#     fourteen resource types.
class CommonFields(TypedDict):
    """`id`, `created_at`, `updated_at` and `version` (PRD §2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Bridge(CommonFields, total=False):
    """A structure in the National Bridge Inventory (PRD §3.1)."""

    # Client-supplied identity and physical facts
    nbi_structure_number: str
    name: str
    owner_agency: str
    structure_type: str
    deck_area_sqm: float
    year_built: int
    adt: int
    detour_length_km: float
    spans_water: bool
    underwater_elements: bool
    fracture_critical: bool
    # Live component ratings, seeded at creation then owned by acceptance
    deck_rating: int
    superstructure_rating: int
    substructure_rating: int
    min_nbi_rating: int
    # Condition rollup published by inspection acceptance
    bridge_health_index: Optional[float]
    inventoried_quantity_total: float
    deficiency_pct: float
    # Frequency policy (PRD §2.11)
    inspection_interval_months: int
    underwater_interval_months: Optional[int]
    last_routine_inspection_date: Optional[str]
    last_underwater_inspection_date: Optional[str]
    next_inspection_due_date: Optional[str]
    next_underwater_due_date: Optional[str]
    # Posture, posting and rating mirrors (PRD §2.11, §3.4)
    service_posture: str
    posting_required: bool
    posted_limit_tons: Optional[float]
    operating_rating_tons: Optional[float]
    inventory_rating_tons: Optional[float]
    governing_load_rating_id: Optional[str]
    # Scour and finding compliance (PRD §3.5, §3.6)
    scour_status: str
    poa_compliant: bool
    open_critical_finding_count: int


class Personnel(CommonFields, total=False):
    """A roster entry (PRD §3.1, §2.10)."""

    full_name: str
    agency: str
    nbis_refresher_expiry_date: str
    team_leader_certified: bool
    underwater_diver_certified: bool
    fracture_critical_certified: bool
    load_rating_engineer_licensed: bool
    pe_license_number: Optional[str]
    qualification_status: str


class Inspection(CommonFields, total=False):
    """A field inspection report (PRD §3.2, §3.3)."""

    bridge_id: str
    inspection_type: str
    status: str
    team_leader_id: str
    qa_reviewer_id: Optional[str]
    field_window_start: str
    field_window_end: str
    notes: Optional[str]
    inspection_date: Optional[str]
    submitted_at: Optional[str]
    qa_claimed_at: Optional[str]
    accepted_at: Optional[str]
    returned_count: int
    qa_escalation_required: bool
    # Element rollups (PRD §3.2)
    element_count: int
    reported_quantity_total: float
    deficient_quantity_total: float
    photo_count_total: int
    quantity_balanced: bool
    # Condition arithmetic frozen at submit (PRD §3.3)
    deck_group_ehi: Optional[float]
    superstructure_group_ehi: Optional[float]
    substructure_group_ehi: Optional[float]
    computed_deck_rating: Optional[int]
    computed_superstructure_rating: Optional[int]
    computed_substructure_rating: Optional[int]
    bridge_health_index: Optional[float]


class ElementCondition(CommonFields, total=False):
    """One national bridge element row inside a report (PRD §3.2)."""

    inspection_id: str
    element_key: str
    element_group: str
    unit: str
    total_quantity: float
    cs1_qty: float
    cs2_qty: float
    cs3_qty: float
    cs4_qty: float
    photo_count: int
    defect_notes: Optional[str]
    # Derived on every write
    reported_sum: float
    balanced: bool
    deficient_quantity: float
    element_health_index: float


class CriticalFinding(CommonFields, total=False):
    """A critical finding with its three orthogonal dimensions (PRD §3.5)."""

    bridge_id: str
    source_inspection_id: str
    element_condition_id: Optional[str]
    severity: str
    description: str
    finding_status: str
    notification_status: str
    restriction_action: str
    notification_due_at: str
    notification_late: bool
    restriction_authorized_by_id: Optional[str]
    restriction_imposed_at: Optional[str]
    mitigation_note: Optional[str]
    resolution_note: Optional[str]


class NotificationLog(TypedDict, total=False):
    """
    An immutable notification audit record (PRD §2.5, §3.5).

    PRD §2.5: "A notification log entry is an immutable audit record: it carries
    `id` and `created_at` only. It has no `updated_at` field and no `version`
    field at all". This shape therefore deliberately does NOT inherit
    CommonFields.
    """

    id: str
    created_at: str
    critical_finding_id: str
    tier: str
    channel: str
    recipient_label: str
    sent_at: str
    late: bool


class LoadRating(CommonFields, total=False):
    """A load rating with both variant results (PRD §3.4)."""

    bridge_id: str
    source_inspection_id: str
    method: str
    rating_vehicle: str
    capacity_c_kn_m: float
    dead_load_dc_kn_m: float
    dead_load_dw_kn_m: float
    live_load_ll_kn_m: float
    impact_im_factor: float
    system_factor_phi_s: float
    resistance_factor_phi: float
    condition_factor_phi_c: float
    rating_factor_operating: float
    rating_factor_inventory: float
    operating_rating_tons: float
    inventory_rating_tons: float
    posting_required: bool
    posted_limit_tons: Optional[float]
    rating_status: str
    sealed_by_id: Optional[str]
    approved_by_id: Optional[str]
    rating_effective_date: Optional[str]
    rejection_note: Optional[str]


class PermitApplication(CommonFields, total=False):
    """An overweight-permit application (PRD §3.7)."""

    permit_number: str
    carrier_name: str
    axle_loads_tons: List[float]
    route_bridge_ids: List[str]
    speed_category: str
    axle_count: int
    gross_weight_tons: float
    status: str
    recommended_decision: str
    governing_analysis_min_rf: Optional[float]
    decision_note: Optional[str]
    decided_at: Optional[str]
    revoked_at: Optional[str]


class PermitBridgeAnalysis(CommonFields, total=False):
    """One per-bridge permit analysis row (PRD §3.7)."""

    permit_application_id: str
    bridge_id: str
    sequence_index: int
    governing_load_rating_id: Optional[str]
    permit_live_load_kn_m: Optional[float]
    permit_impact_factor: Optional[float]
    rating_factor_permit: Optional[float]
    analysis_result: str
    result_reason: str


class ScourEvaluation(CommonFields, total=False):
    """A scour evaluation record (PRD §3.6)."""

    bridge_id: str
    evaluated_by_id: str
    evaluation_method: str
    scour_code: int
    foundation_type: Optional[str]
    observed_scour_depth_m: float
    derived_scour_status: str
    status: str
    finalized_at: Optional[str]


class PlanOfAction(CommonFields, total=False):
    """A scour plan of action (PRD §3.6)."""

    bridge_id: str
    scour_evaluation_id: str
    monitoring_frequency_months: Optional[int]
    closure_trigger_stage_m: Optional[float]
    countermeasure_type: str
    status: str
    revision_count: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    approved_by_id: Optional[str]
    return_note: Optional[str]


class ProgramCycle(CommonFields, total=False):
    """A fiscal-year programming cycle and its budget waterfall (PRD §3.8)."""

    fiscal_year: int
    authorized_budget_cents: int
    ranking_policy: str
    reserve_pct: float
    reserve_cents: int
    available_cents: int
    committed_cents: int
    remaining_cents: int
    unprogrammed_cost_cents: int
    identified_count: int
    programmed_count: int
    deferred_count: int
    status: str
    locked_at: Optional[str]
    submitted_at: Optional[str]
    closed_at: Optional[str]


class ProjectCandidate(CommonFields, total=False):
    """A capital project candidate with its scored priority (PRD §3.8)."""

    program_cycle_id: str
    bridge_id: str
    source_inspection_id: str
    origin: str
    justification: Optional[str]
    work_type: str
    estimated_cost_cents: int
    priority_score: float
    ranking_policy_applied: str
    status: str
    programmed_at: Optional[str]
    withdrawn_at: Optional[str]
    deferred_at: Optional[str]


class FederalSubmission(CommonFields, total=False):
    """A statewide compliance package (PRD §3.9)."""

    program_cycle_id: str
    submission_type: str
    status: str
    total_bridge_count: int
    overdue_inspection_count: int
    inspection_compliance_pct: float
    poa_noncompliant_count: int
    open_immediate_finding_count: int
    error_count: int
    rejection_reason_code: str
    submitted_by_user_id: Optional[str]
    reviewer_user_id: Optional[str]
    submitted_at: Optional[str]
    reviewed_at: Optional[str]


class ComplianceSummary(TypedDict, total=False):
    """The per-structure computed compliance read (PRD §3.1, §3.9)."""

    bridge_id: str
    inspection_interval_months: int
    next_inspection_due_date: Optional[str]
    next_underwater_due_date: Optional[str]
    routine_overdue: bool
    underwater_overdue: bool
    poa_compliant: bool
    open_critical_finding_count: int
    service_posture: str
    min_nbi_rating: int
    bridge_health_index: Optional[float]


class AllocationSummary(TypedDict, total=False):
    """The cycle's computed budget-identity read (PRD §3.8)."""

    program_cycle_id: str
    authorized_budget_cents: int
    reserve_cents: int
    available_cents: int
    committed_cents: int
    remaining_cents: int
    identified_count: int
    programmed_count: int
    deferred_count: int
    unprogrammed_cost_cents: int
    identity_holds: bool


# A loose alias for response bodies whose exact shape a test does not pin.
JsonDict = Dict[str, Any]
