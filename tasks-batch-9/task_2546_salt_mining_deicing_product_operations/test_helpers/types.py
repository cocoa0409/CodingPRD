"""
TypedDict shapes for every resource family in the Salt Deicing Operations API.

Field names are exactly the names the PRD uses on the wire. Per PRD §2.4 eleven of
the twelve families carry `updated_at` and `version` alongside `id` and
`created_at`; `GroundControlInspection` is the exception and carries only `id` and
`created_at`, so its shape below deliberately omits both.
"""

from typing import Optional, TypedDict


class TimestampedResource(TypedDict):
    """The four common properties of the eleven versioned families (PRD §2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Mine(TimestampedResource):
    name: str
    state_code: str
    rated_hoist_tons_per_day: float
    ground_control_plan_version: int
    hoist_state: str
    compliance_state: str
    effective_hoist_tons_per_day: float
    scheduled_hoist_tons_open: float
    producing_panel_count: int
    last_compliance_action_at: Optional[str]


class Panel(TimestampedResource):
    mine_id: str
    panel_code: str
    gross_tons_in_place: float
    extraction_ratio_pct: float
    grade_pct_nacl: float
    insolubles_pct: float
    pillar_recovery_allowed: bool
    recoverable_tons: float
    mined_tons: float
    status: str
    ground_control_defect_count: int
    open_defect: bool
    suspended_by_user_id: Optional[str]


class GroundControlInspection(TypedDict):
    """Immutable append-only observation: no `updated_at`, no `version` (PRD §2.4)."""

    id: str
    created_at: str
    panel_id: str
    roof_span_ft: float
    convergence_rate_in_per_day: float
    finding: str
    inspector_user_id: str
    caused_suspension: bool


class ProductionRun(TimestampedResource):
    mine_id: str
    panel_id: str
    planned_tons: float
    hoist_window_start: str
    hoist_window_end: str
    planned_tons_per_hour: float
    hoisted_tons: float
    status: str
    held_reason: Optional[str]
    open_batch_count: int


class TreatmentBatch(TimestampedResource):
    production_run_id: str
    depot_id: str
    product_line: str
    screen_spec: str
    anticaking_ppm: float
    corrosion_inhibitor_pct: float
    input_tons: float
    moisture_pct: float
    storage_kind: str
    yield_tons: float
    purity_pct_nacl: float
    qc_state: str
    rework_count: int
    created_by_user_id: str
    qc_decided_by_user_id: Optional[str]


class Depot(TimestampedResource):
    name: str
    state_code: str
    covered_capacity_tons: float
    open_pad_capacity_tons: float
    loadout_rate_tons_per_hour: float
    outbound_freight_rate_per_ton: float
    depot_state: str
    covered_stored_tons: float
    open_pad_stored_tons: float
    covered_utilization_pct: float
    storm_state_set_by_user_id: Optional[str]


class StockpileLot(TimestampedResource):
    depot_id: str
    treatment_batch_id: str
    product_line: str
    purity_pct_nacl: float
    storage_kind: str
    tons_on_hand: float
    tons_reserved: float
    tons_available: float
    lot_state: str
    quarantine_reason: Optional[str]


class Shipment(TimestampedResource):
    stockpile_lot_id: str
    origin_depot_id: str
    destination_depot_id: str
    mode: str
    tons: float
    load_window_start: str
    load_window_end: str
    destination_storage_kind: str
    required_gap_minutes: int
    status: str
    received_lot_id: Optional[str]


class SeasonForecast(TimestampedResource):
    season_code: str
    region_code: str
    normal_season_tons: float
    severity_index: int
    prior_season_1_actual_tons: float
    prior_season_2_actual_tons: float
    prior_season_3_actual_tons: float
    method: str
    preseason_lock_date: str
    target_tons_severity_weighted: float
    target_tons_trailing_baseline: float
    binding_target_tons: float
    variant_spread_tons: float


class BidContract(TimestampedResource):
    season_forecast_id: str
    customer_name: str
    jurisdiction_level: str
    state_code: str
    product_line: str
    committed_tons: float
    guaranteed_price_per_ton: float
    min_take_pct: float
    max_take_pct: float
    failure_to_supply_penalty_per_ton: float
    price_guarantee_cap_pct: float
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    contract_value_usd: Optional[float]
    fulfilled_tons: float
    open_committed_tons: float
    take_pct: float
    penalty_accrued_usd: float
    season_penalty_usd: Optional[float]
    penalty_reconciliation_delta_usd: Optional[float]
    supply_reliability_score: float
    breach_watch: bool


class DeliveryOrder(TimestampedResource):
    bid_contract_id: str
    depot_id: str
    requested_tons: float
    required_by: str
    storm_priority: str
    market_index_price_per_ton: float
    allocated_tons: float
    shorted_tons: float
    status: str
    penalty_state: str
    shortfall_penalty_usd: float
    product_subtotal_usd: Optional[float]
    freight_subtotal_usd: Optional[float]
    storm_surcharge_usd: Optional[float]
    guarantee_credit_usd: Optional[float]
    invoice_total_usd: Optional[float]
    delivered_at: Optional[str]


class Allocation(TimestampedResource):
    delivery_order_id: str
    stockpile_lot_id: str
    tons: float
    origin: str
    rank_position: int
    state: str


# ─── Computed read views (PRD §2.10) ──────────────────


class MineHoistCapacityView(TypedDict):
    rated_hoist_tons_per_day: float
    hoist_factor: float
    compliance_factor: float
    effective_hoist_tons_per_day: float
    mine_hourly_capacity: float
    scheduled_hoist_tons_open: float
    scheduled_run_count: int


class DepotStoragePostureView(TypedDict):
    depot_state: str
    covered_capacity_tons: float
    covered_stored_tons: float
    open_pad_capacity_tons: float
    open_pad_stored_tons: float
    covered_utilization_pct: float
    auto_surge_threshold_pct: float
    reserved_tons: float


class ContractLedgerView(TypedDict):
    committed_tons: float
    fulfilled_tons: float
    open_committed_tons: float
    take_pct: float
    take_band_consumed_tons: float
    take_band_limit_tons: float
    penalty_accrued_usd: float
    accrued_penalty_order_count: int
    supply_reliability_score: float
    breach_watch: bool
    preseason_coverage_tons: float
    preseason_coverage_required_tons: float
