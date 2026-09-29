"""TypedDict shapes for the entities described in PRD §3.

PRD §2.5 fixes the common-field inventory: every persisted row carries `id`,
`created_at`, `updated_at` and `version`, with one documented exception —
ClaimAssessment, which carries only `id` and `created_at` because it is an
append-only bench observation that is superseded rather than edited.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """Common fields for every versioned entity (PRD §2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableCommonFields(TypedDict):
    """Common fields for ClaimAssessment only (PRD §2.5)."""

    id: str
    created_at: str


class ServiceCenter(CommonFields):
    name: str
    region_code: str
    liability_cap_cents: int
    bench_capacity_blocks_per_day: int
    open_liability_cents: int
    liability_utilization_pct: float
    liability_posture: str
    active_queue_depth: int
    current_surge_multiplier: float
    breached_commitment_count: int
    last_queue_review_at: Optional[str]


class GearModel(CommonFields):
    model_code: str
    name: str
    category: str
    msrp_cents: int
    release_year: int
    warranty_years: int
    lifetime_warranty: bool
    discontinued_at: Optional[str]
    successor_model_id: Optional[str]
    parts_support_status: str
    defect_claim_count: int
    wear_denial_count: int
    irreparable_count: int
    repairability_flag: str


class Customer(CommonFields):
    email: str
    full_name: str
    loyalty_tier: str
    lifetime_claim_count: int
    trade_in_credit_cents: int


class GearItem(CommonFields):
    gear_model_id: str
    owner_customer_id: str
    serial_number: str
    purchase_date: str
    purchase_price_cents: int
    proof_of_purchase_type: str
    proof_of_purchase_ref: Optional[str]
    condition_grade: str
    disposition_status: str
    age_months: int
    warranty_state: str
    replacement_value_depreciated_cents: int
    replacement_value_successor_cents: Optional[int]
    trade_in_credit_cents: int
    refurb_list_price_cents: Optional[int]
    resale_price_cents: Optional[int]


class WarrantyClaim(CommonFields):
    service_center_id: str
    gear_item_id: str
    intake_kind: str
    reported_defect_type: str
    customer_narrative: Optional[str]
    status: str
    proof_verified: bool
    submitted_at: Optional[str]
    info_request_count: int
    assessment_count: int
    latest_determination: Optional[str]
    latest_repair_cost_cents: Optional[int]
    decision: Optional[str]
    decision_threshold_pct: Optional[int]
    repair_ratio_pct: Optional[float]
    decision_by_role: Optional[str]
    decided_at: Optional[str]


class ClaimAssessment(ImmutableCommonFields):
    """PRD §2.5: no `updated_at`, no `version` — append-only."""

    warranty_claim_id: str
    assessor_technician_id: str
    determination: str
    defect_notes: Optional[str]
    required_work_types: List[str]
    estimated_labor_lines: List[Dict[str, Any]]
    estimated_parts_cents: int
    estimated_repair_cost_cents: int
    is_superseded: bool


class Technician(CommonFields):
    service_center_id: str
    full_name: str
    employee_code: str
    status: str
    certifications: List[Dict[str, Any]]
    scheduled_minutes_open: int
    completed_minutes: int


class WorkBlock(CommonFields):
    technician_id: str
    repair_order_id: str
    work_type: str
    start_at: str
    end_at: str
    duration_minutes: int
    actual_minutes: Optional[int]
    status: str
    routed_by_selector: bool


class SurgeWindow(CommonFields):
    service_center_id: str
    label: str
    start_date: str
    end_date: str
    multiplier: float
    status: str


class RepairOrder(CommonFields):
    service_center_id: str
    gear_item_id: str
    warranty_claim_id: str
    expedite_requested: bool
    order_kind: str
    work_status: str
    billing_status: str
    required_work_types: List[str]
    queue_depth_snapshot: int
    surge_multiplier_applied: float
    parts_wait_days: int
    promised_days: int
    promised_return_at: str
    commitment_breached: bool
    qc_fail_count: int
    provisional_estimate_total_cents: Optional[int]
    final_invoice_total_cents: Optional[int]
    paid_amount_cents: int
    released_at: Optional[str]


class RepairEstimate(CommonFields):
    repair_order_id: str
    labor_lines: List[Dict[str, Any]]
    parts_lines: List[Dict[str, Any]]
    variant: str
    status: str
    labor_subtotal_cents: int
    parts_subtotal_cents: int
    shop_supply_fee_cents: int
    subtotal_cents: int
    loyalty_discount_cents: int
    expedite_fee_cents: int
    tax_cents: int
    total_cents: int
    valid_until: Optional[str]
    decided_at: Optional[str]


class PartLot(CommonFields):
    gear_model_id: str
    part_code: str
    part_kind: str
    on_hand_units: int
    unit_price_cents: int
    low_watermark_units: int
    substitution_allowed: bool
    substitute_for_part_code: Optional[str]
    reserved_units: int
    available_units: int
    status: str


class PartsReservation(CommonFields):
    repair_order_id: str
    part_lot_id: str
    required_part_code: str
    units: int
    is_substitution: bool
    status: str
    settled_at: Optional[str]


class LiabilityEntry(CommonFields):
    warranty_claim_id: str
    basis: str
    valuation_variant: str
    reserved_amount_cents: int
    status: str
    release_reason: Optional[str]
    released_at: Optional[str]
