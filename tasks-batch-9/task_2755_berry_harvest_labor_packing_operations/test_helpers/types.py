"""
TypedDict shapes for every resource family of the Berry Harvest Ops API.

Field lists follow PRD section 3. Per PRD section 2.4 ten of the eleven
families carry the full audit triple ``created_at``, ``updated_at`` and
``version``; ``WaterTest`` is the deliberate exception and carries only
``id`` and ``created_at``, because "the agricultural-water register is
append-only".
"""

from typing import Any, Dict, List, Optional, TypedDict


class AuditedResource(TypedDict):
    """The audit triple shared by the ten versioned families (PRD 2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Block(AuditedResource, total=False):
    name: str
    variety: str
    acres: float
    planting_year: int
    irrigation_source_code: str
    water_sample_count: int
    water_geomean_mpn: Optional[float]
    last_sample_date: Optional[str]
    water_status: str
    manual_quarantine_active: bool
    quarantined_by_user_id: Optional[str]
    quarantine_reason_code: Optional[str]
    food_safety_posture: str


class WaterTest(TypedDict, total=False):
    """PRD 2.4: "A water sample carries only `id` and `created_at`."."""

    id: str
    created_at: str
    block_id: str
    sample_date: str
    generic_ecoli_mpn: int
    single_sample_exceedance: bool
    resulting_water_status: str
    recorded_by_user_id: str


class Crew(AuditedResource, total=False):
    name: str
    labor_program: str
    supervisor_user_id: str
    planned_head_count: int
    contract_start_date: str
    contract_end_date: str
    status: str
    picker_count: int
    support_plan_complete: bool
    housing_unit_code: Optional[str]
    transport_route_code: Optional[str]
    beds_confirmed: int
    vehicle_seats: int
    accrued_wage_cents: int
    settled_wage_cents: int
    reconciliation_delta_cents: int


class Picker(AuditedResource, total=False):
    crew_id: str
    full_name: str
    labor_program: str
    hygiene_training_on: Optional[str]
    hygiene_training_expires_on: Optional[str]
    total_clamshells_lifetime: int
    total_hours_lifetime: float
    avg_lbs_per_hour: float


class HarvestWindow(AuditedResource, total=False):
    block_id: str
    crew_id: str
    start_at: str
    end_at: str
    window_hours: float
    forecast_brix: float
    planned_volume_lbs: float
    piece_rate_cents_per_clamshell: int
    clamshell_net_weight_lbs: float
    status: str
    effective_pick_rate_lbs_per_hour: Optional[float]
    required_picker_count: Optional[int]
    harvested_clamshells: int
    packed_lbs: float
    suspended_reason_code: Optional[str]
    cancel_reason_code: Optional[str]


class PickSession(AuditedResource, total=False):
    harvest_window_id: str
    picker_id: str
    work_date: str
    status: str
    hours_worked: float
    clamshells_filled: int
    culled_clamshells: int
    cull_rate: Optional[float]
    quality_flag: str
    effective_piece_rate_cents: int
    piece_cents: int
    guarantee_floor_cents: int
    makeup_cents: int
    gross_cents: int
    housing_deduction_cents: int
    net_cents: int
    tally_revision_count: int
    payroll_run_id: Optional[str]
    tallied_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    dispute_reason_code: Optional[str]
    void_reason_code: Optional[str]


class PayrollRun(AuditedResource, total=False):
    crew_id: str
    period_start_date: str
    period_end_date: str
    status: str
    bound_session_count: int
    period_hours: Optional[float]
    period_piece_cents: Optional[int]
    period_floor_cents: Optional[int]
    period_makeup_cents: Optional[int]
    period_deduction_cents: Optional[int]
    settled_gross_cents: Optional[int]
    settled_net_cents: Optional[int]
    accrued_gross_cents: Optional[int]
    reconciliation_delta_cents: Optional[int]
    locked_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]


class CoolingTunnel(AuditedResource, total=False):
    name: str
    slot_capacity: int
    target_pulp_temp_f: float
    committed_slots: int


class FruitLot(AuditedResource, total=False):
    harvest_window_id: str
    block_id: str
    variety: str
    grade: str
    clamshell_count: int
    clamshell_net_weight_lbs: float
    pick_date: str
    pack_completed_at: str
    field_pulp_temp_f: float
    net_packed_lbs: float
    available_lbs: float
    allocated_lbs: float
    repack_out_lbs: float
    cull_lbs: float
    optical_reject_lbs: float
    traceability_code: str
    cold_chain_status: str
    disposition_status: str
    food_safety_hold: bool
    source_lot_id: Optional[str]
    cooling_tunnel_id: Optional[str]
    pallet_slots: Optional[int]
    cool_start_at: Optional[str]
    planned_cool_end_at: Optional[str]
    cool_complete_at: Optional[str]
    entry_pulp_temp_f: Optional[float]
    exit_pulp_temp_f: Optional[float]
    field_delay_hours: Optional[float]
    cool_hours: Optional[float]
    forecast_shelf_life_days: Optional[int]
    verified_shelf_life_days: Optional[int]
    shelf_life_expires_on: Optional[str]
    reject_reason_code: Optional[str]


class BuyerCommitment(AuditedResource, total=False):
    buyer_name: str
    buyer_user_id: str
    variety: str
    volume_commitment_lbs: float
    price_cents_per_lb: int
    shelf_life_guarantee_days: int
    window_start_date: str
    window_end_date: str
    status: str
    committed_lbs: float
    shipped_lbs: float
    open_lbs: Optional[float]
    fill_pct: float
    fill_status: str
    risk_flag: str
    settled_revenue_cents: Optional[int]
    shortfall_penalty_cents: Optional[int]
    settled_net_cents: Optional[int]


class LotAllocation(AuditedResource, total=False):
    fruit_lot_id: str
    buyer_commitment_id: str
    allocated_lbs: float
    status: str
    shipped_at: Optional[str]
    release_reason_code: Optional[str]
    shelf_life_shortfall_days: Optional[int]
    line_gross_cents: Optional[int]
    line_discount_cents: Optional[int]
    line_net_cents: Optional[int]


class TraceabilitySummary(TypedDict, total=False):
    """The computed roll-up of PRD 3.1 "Traceability roll-up"."""

    block_id: str
    block_name: str
    variety: str
    water_status: str
    food_safety_posture: str
    lot_count: int
    pick_date_count: int
    total_packed_lbs: float
    shipped_lbs: float
    held_lot_count: int
    rejected_lot_count: int
    earliest_pick_date: Optional[str]
    latest_pick_date: Optional[str]


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
