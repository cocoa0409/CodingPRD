"""
Response shapes.

Every entity except CounterFirm carries the four common properties `id`,
`created_at`, `updated_at` and `version`.  CounterFirm is the declared
exception: it carries only `id` and `created_at`, so `CounterFirm` below
deliberately omits `updated_at` and `version`.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Category(CommonFields):
    code: str
    name: str
    count_cadence_days: int
    variance_tolerance_units: int
    variance_tolerance_value_cents: int
    landed_cost_uplift_bps: int
    reader_mode_required: str
    min_accuracy_pct: float
    auto_correct_negative: bool


class Store(CommonFields):
    code: str
    name: str
    reader_capability: str
    overhead_reader_capacity: int
    total_position_count: int
    blocked_position_count: int
    restricted_position_count: int
    accuracy_index_bps: int
    fulfillment_status: str


class Vendor(CommonFields):
    code: str
    name: str
    tag_compliance_score_bps: int
    required_verification_sample_pct: int
    shortage_event_count: int
    lifetime_chargeback_gross_cents: int
    credited_cents: int
    chargeback_balance_cents: int


class CounterFirm(TypedDict):
    """No updated_at and no version: CounterFirm is the immutable exception."""

    id: str
    created_at: str
    code: str
    name: str
    certification_level: str
    max_lines_per_pass: int


class Item(CommonFields):
    category_id: str
    primary_vendor_id: str
    sku: str
    description: str
    unit_cost_cents: int
    retail_price_cents: int
    tag_encoding_scheme: str
    epc_prefix_length: int
    tag_required: bool


class StockPosition(CommonFields):
    store_id: str
    item_id: str
    baseline_on_hand_units: int
    reserved_units: int
    on_hand_units: int
    phantom_units: int
    book_value_cents: int
    last_counted_at: Optional[str]
    last_count_system_units: int
    last_count_book_value_cents: int
    last_variance_units: int
    last_variance_value_cents: int
    unit_accuracy_pct: float
    value_accuracy_pct: float
    tag_integrity_hold: bool
    negative_correction_count: int
    promising_state: str


class TagBatch(CommonFields):
    vendor_id: str
    item_id: str
    destination_store_id: str
    encoding_scheme: Optional[str]
    epc_prefix: Optional[str]
    quantity_encoded: int
    status: str
    rework_round: int
    required_sample_units: int
    sampled_units: int
    readable_units: int
    duplicate_epc_count: int
    unencoded_units: int
    read_rate_bps: int
    verification_outcome: Optional[str]


class CountSchedule(CommonFields):
    store_id: str
    category_id: str
    cadence_days: int
    reader_mode: str
    next_due_date: str
    status: str
    completed_cycle_count: int


class CountTask(CommonFields):
    count_schedule_id: str
    store_id: str
    category_id: str
    reader_mode: str
    window_start: str
    window_end: str
    status: str
    recount_round: int
    in_scope_position_count: int
    counted_line_count: int
    coverage_pct: float
    variance_line_count: int
    total_variance_value_cents: int


class CountLine(CommonFields):
    count_task_id: str
    item_id: str
    stock_position_id: str
    counted_units: int
    system_units_snapshot: int
    read_mode_used: str
    variance_units: int
    variance_value_cents: int
    within_tolerance: bool


class VarianceInvestigation(CommonFields):
    count_line_id: str
    store_id: str
    shrink_period_id: str
    variance_units: int
    variance_value_cents: int
    status: str
    assigned_investigator_id: Optional[str]
    proposed_root_cause: Optional[str]
    approved_root_cause: Optional[str]
    proposed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    proposal_round: int
    evidence_note: Optional[str]


class Adjustment(CommonFields):
    stock_position_id: str
    investigation_id: Optional[str]
    delta_units: int
    reason_code: str
    value_impact_cents: int
    authority_threshold_cents: int
    approval_state: str
    posting_state: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    posted_at: Optional[str]
    reversed_at: Optional[str]


class ShrinkPeriod(CommonFields):
    store_id: str
    period_start: str
    period_end: str
    sales_at_cost_cents: int
    status: str
    theft_cents: int
    damage_cents: int
    process_error_cents: int
    vendor_shortage_cents: int
    unresolved_cents: int
    total_attributable_variance_cents: int
    provisional_total_shrink_cents: int
    final_total_shrink_cents: int
    shrink_rate_bps: int
    reopen_count: int
    chargeback_issued_vendor_ids: List[str]


class PhysicalInventory(CommonFields):
    store_id: str
    counter_firm_id: str
    scheduled_start_date: str
    scheduled_end_date: str
    recount_threshold_bps: int
    status: str
    recount_round: int
    line_count: int
    book_value_cents: int
    counted_value_cents: int
    net_variance_cents: int
    net_variance_bps: int
    certified_at: Optional[str]


class PhysicalInventoryLine(CommonFields):
    physical_inventory_id: str
    item_id: str
    counted_units: int
    book_units_snapshot: int
    book_value_snapshot_cents: int
    pass_round: int
    variance_units: int
    variance_value_cents: int
    superseded: bool
