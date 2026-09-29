"""TypedDict shapes for every entity in the PRD.

PRD 2.4 defines two tiers of common fields. Nineteen entity types carry
``id``, ``created_at``, ``updated_at`` and ``version``; ``CommodityIndexPoint``
is the sole exception and carries only ``id`` and ``created_at`` -- it has no
``updated_at`` and no ``version``, so ``CommodityIndexPoint`` below omits both.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VersionedEntity(TypedDict):
    """PRD 2.4 tier one: the nineteen version-tracked entity types."""

    id: str
    created_at: str
    updated_at: str
    version: int


class EngineeredOrder(VersionedEntity, total=False):
    order_number: str
    customer_name: str
    product_family: str
    rated_kv: float
    contract_value_cents: int
    sold_at: str
    promised_ship_at: str
    owning_sales_user_id: str
    engineering_status: str
    fulfillment_status: str
    production_posture: str
    posture_reason_codes: List[str]
    released_drawing_revision: Optional[int]
    net_contract_value_cents: int
    escalation_accepted_total_cents: int
    warranty_credit_total_cents: int
    billed_to_date_cents: int
    cancelled_reason: Optional[str]


class SubmittalDrawing(VersionedEntity, total=False):
    engineered_order_id: str
    drawing_set_code: str
    authored_by_user_id: str
    reviewed_by_user_id: Optional[str]
    revision_round: int
    supersedes_drawing_id: Optional[str]
    status: str
    notes_count: int
    as_noted_changes_bill_of_material: bool
    submitted_at: Optional[str]
    disposition_at: Optional[str]


class EscalationClause(VersionedEntity, total=False):
    engineered_order_id: str
    copper_weight_bp: int
    aluminum_weight_bp: int
    core_steel_weight_bp: int
    escalatable_base_cents: int
    base_index_month: str
    cap_bp: int
    collar_bp: int
    de_escalation_enabled: bool
    final_window_end_month: str
    status: str


class CommodityIndexPoint(TypedDict, total=False):
    """PRD 2.4: carries only ``id`` and ``created_at`` -- no version field."""

    id: str
    created_at: str
    commodity: str
    index_month: str
    index_value: float
    published_at: str
    is_provisional: bool


class EscalationAdjustment(VersionedEntity, total=False):
    engineered_order_id: str
    escalation_clause_id: str
    variant: str
    status: str
    prepared_by_user_id: str
    accepted_by_user_id: Optional[str]
    copper_component_cents: int
    aluminum_component_cents: int
    core_steel_component_cents: int
    raw_movement_cents: int
    adjustment_amount_cents: int
    cap_applied: bool
    collar_absorbed: bool
    index_months_used: List[str]
    recalculation_round: int
    dispute_reason: Optional[str]


class Supplier(VersionedEntity, total=False):
    supplier_code: str
    legal_name: str
    region: str
    status: str
    quality_index_trailing: float
    quality_index_lifetime: float
    attributed_failure_count: int
    receipt_event_count: int
    probation_entered_at: Optional[str]


class LongLeadComponent(VersionedEntity, total=False):
    supplier_id: str
    part_number: str
    category: str
    lead_time_days: int
    quantity_on_hand: int
    quantity_available: int
    quantity_reserved: int
    quantity_committed: int
    quantity_consumed: int
    allocation_policy: str
    status: str
    quarantine_reason: Optional[str]


class ComponentAllocation(VersionedEntity, total=False):
    long_lead_component_id: str
    engineered_order_id: str
    quantity: int
    priority_class: int
    need_by_date: str
    status: str
    release_penalty_cents: int
    preempted_for_allocation_id: Optional[str]
    committed_at: Optional[str]
    released_at: Optional[str]


class TestBay(VersionedEntity, total=False):
    bay_code: str
    max_kv: float
    changeover_buffer_hours: int
    supports_impulse: bool
    status: str
    scheduled_hours_total: float


class FactoryAcceptanceTest(VersionedEntity, total=False):
    engineered_order_id: str
    test_bay_id: Optional[str]
    test_duration_hours: int
    witness_required: bool
    requires_impulse: bool
    retest_of_fat_id: Optional[str]
    attempt_number: int
    status: str
    window_start_at: Optional[str]
    window_end_at: Optional[str]
    confirmed_witness_count: int
    run_by_user_id: Optional[str]
    started_at: Optional[str]
    concluded_at: Optional[str]
    result: Optional[str]


class WitnessParty(VersionedEntity, total=False):
    party_code: str
    display_name: str
    party_type: str
    home_region: str
    daily_witness_capacity: int
    credential_expires_at: str
    status: str


class WitnessAssignment(VersionedEntity, total=False):
    factory_acceptance_test_id: str
    witness_party_id: str
    travel_region: str
    blackout_days: int
    status: str
    confirmed_at: Optional[str]
    decline_reason: Optional[str]


class TestReport(VersionedEntity, total=False):
    factory_acceptance_test_id: str
    winding_temp_rise_c: float
    temp_rise_limit_c: float
    short_circuit_current_ka: float
    arc_duration_ms: int
    working_distance_mm: int
    impulse_withstand_kv: Optional[float]
    impulse_required_kv: Optional[float]
    pass_result: str
    failed_criteria: List[str]
    status: str
    issued_at: Optional[str]


class ComplianceLabel(VersionedEntity, total=False):
    engineered_order_id: str
    submittal_drawing_id: str
    test_report_id: str
    generated_by_user_id: str
    verified_by_user_id: Optional[str]
    pinned_drawing_revision: int
    status: str
    incident_energy_cal_cm2: Optional[float]
    ppe_category: Optional[int]
    arc_flash_boundary_mm: Optional[int]
    rating_text: Optional[str]
    void_reason: Optional[str]
    issued_at: Optional[str]


class ShipmentRelease(VersionedEntity, total=False):
    engineered_order_id: str
    stage_index: int
    stage_share_bp: int
    is_final_stage: bool
    status: str
    stage_billing_cents: int
    storage_fee_accrued_cents: int
    carrier_reference: Optional[str]
    cleared_at: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]


class SiteStorageAgreement(VersionedEntity, total=False):
    shipment_release_id: str
    storage_start_at: str
    storage_end_at: Optional[str]
    crate_count: int
    insured_value_cents: int
    status: str
    billable_days: int
    storage_subtotal_cents: int
    insurance_surcharge_cents: int
    long_stay_discount_cents: int
    total_fee_cents: int
    waived_by_user_id: Optional[str]


class CommissioningJob(VersionedEntity, total=False):
    engineered_order_id: str
    shipment_release_id: str
    mobilization_at: str
    lead_field_user_id: str
    status: str
    open_punch_count: int
    blocking_punch_count: int
    completion_ratio_bp: int
    demobilization_round: int
    startup_certificate_issued: bool
    energized_at: Optional[str]


class PunchListItem(VersionedEntity, total=False):
    commissioning_job_id: str
    severity: str
    description_text: str
    status: str
    reject_count: int
    assigned_to_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    closed_at: Optional[str]


class WarrantyClaim(VersionedEntity, total=False):
    engineered_order_id: str
    claim_number: str
    suspect_component_id: Optional[str]
    failure_reported_at: str
    parts_claim_cents: int
    labor_claim_cents: int
    freight_claim_cents: int
    consequential_claim_cents: int
    consequential_covered: bool
    status: str
    rma_number: Optional[str]
    liability_cap_cents: int
    credit_issued_cents: int
    bucket_allocation: Dict[str, int]
    analysis_round: int
    settled_by_user_id: Optional[str]


class FailureAnalysisReport(VersionedEntity, total=False):
    warranty_claim_id: str
    attributed_supplier_id: Optional[str]
    root_cause_code: str
    authored_by_user_id: str
    quarantine_recommended: bool
    defect_weight: int
    status: str
    published_at: Optional[str]
    retraction_reason: Optional[str]


JsonDict = Dict[str, Any]
