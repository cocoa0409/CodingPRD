"""TypedDict shapes for every resource the API returns.

Field names are copied from the PRD verbatim. Every resource carries `id`,
`created_at`, `updated_at` and `version` except the effectiveness test, which
the PRD describes as an immutable audit record carrying only `id` and
`created_at`.
"""

from typing import List, Optional, TypedDict


class HedgePolicy(TypedDict):
    id: str
    policy_code: str
    fiscal_year: int
    max_coverage_pct: float
    min_coverage_pct: float
    max_single_counterparty_pct: float
    max_earnings_volatility_usd: float
    max_tankering_uplift_gallons: float
    min_days_cover: float
    permitted_instrument_types: List[str]
    eligible_fleet_types: List[str]
    status: str
    open_exception_count: int
    created_at: str
    updated_at: str
    version: int


class Counterparty(TypedDict):
    id: str
    counterparty_code: str
    legal_name: str
    credit_rating: str
    credit_limit_usd: float
    status: str
    utilized_credit_usd: float
    posted_collateral_usd: float
    utilization_pct: float
    credit_posture: str
    open_margin_call_count: int
    last_review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    iata_code: str
    name: str
    into_plane_fee_usd_per_gal: float
    avg_daily_liftings_gallons: float
    consortium_member: bool
    consortium_share_pct: float
    consortium_pool_gallons: float
    inventory_gallons: float
    effective_inventory_gallons: float
    days_cover: float
    supply_posture: str
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict):
    id: str
    station_id: str
    contract_ref: str
    index_basis: str
    index_price_usd_per_gal: float
    differential_usd_per_gal: float
    all_in_price_usd_per_gal: float
    term_start_date: str
    term_end_date: str
    min_monthly_gallons: float
    max_monthly_gallons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumptionForecast(TypedDict):
    id: str
    fleet_type: str
    route_group: str
    season: str
    period_start_month: str
    period_end_month: str
    forecast_gallons: float
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HedgeProgram(TypedDict):
    id: str
    policy_id: str
    program_code: str
    period_start_month: str
    period_end_month: str
    route_groups: List[str]
    target_coverage_pct: float
    status: str
    consumption_basis_gallons: float
    hedged_gallons: float
    delta_adjusted_gallons: float
    coverage_pct_notional: float
    coverage_pct_delta: float
    planned_coverage_pct_delta: float
    designated_mtm_usd: float
    undesignated_mtm_usd: float
    earnings_volatility_usd: float
    compliance_posture: str
    open_instrument_count: int
    return_count: int
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HedgeInstrument(TypedDict):
    id: str
    hedge_program_id: str
    counterparty_id: str
    instrument_type: str
    notional_gallons: float
    maturity_month: str
    strike_usd_per_gal: Optional[float]
    floor_strike_usd_per_gal: Optional[float]
    cap_strike_usd_per_gal: Optional[float]
    premium_usd: float
    delta_factor: float
    delta_adjusted_gallons: float
    trade_status: str
    accounting_status: str
    mtm_value_usd: float
    margin_requirement_usd: float
    collateral_posted_usd: float
    cumulative_hedge_change_usd: float
    cumulative_item_change_usd: float
    proposed_by_user_id: str
    executed_at: Optional[str]
    designated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollateralPosting(TypedDict):
    id: str
    counterparty_id: str
    hedge_instrument_id: str
    collateral_type: str
    origin: str
    status: str
    required_amount_usd: float
    posted_amount_usd: float
    posted_at: Optional[str]
    returned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EffectivenessTest(TypedDict):
    """Immutable audit record: `id` and `created_at` only, no version stamp."""

    id: str
    hedge_instrument_id: str
    period_month: str
    hedge_change_usd: float
    hedged_item_change_usd: float
    period_ratio: float
    cumulative_ratio: float
    result: str
    tested_by_user_id: str
    created_at: str


class MarkToMarketRun(TypedDict):
    id: str
    period_month: str
    settlement_index_usd_per_gal: float
    status: str
    instrument_count: int
    total_mtm_usd: float
    designated_mtm_usd: float
    undesignated_mtm_usd: float
    margin_calls_created: int
    settled_instrument_count: int
    computed_at: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict):
    id: str
    flight_number: str
    departure_date: str
    origin_station_id: str
    destination_station_id: str
    fleet_type: str
    planned_block_minutes: int
    planned_burn_gallons: float
    tank_capacity_gallons: float
    payload_lbs: float
    max_takeoff_payload_lbs: float
    landing_weight_lbs: float
    max_landing_weight_lbs: float
    uplift_cap_gallons: float
    actual_block_minutes: Optional[int]
    actual_uplift_gallons: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TankeringDirective(TypedDict):
    id: str
    flight_leg_id: str
    requested_uplift_gallons: float
    status: str
    revision_count: int
    planned_burn_penalty_gallons: float
    planned_gross_savings_usd: float
    planned_penalty_cost_usd: float
    planned_net_savings_usd: float
    pinned_origin_price_usd_per_gal: Optional[float]
    pinned_destination_price_usd_per_gal: Optional[float]
    pinned_origin_contract_ref: Optional[str]
    reconciled_burn_penalty_gallons: Optional[float]
    reconciled_net_savings_usd: Optional[float]
    savings_variance_usd: Optional[float]
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PolicyException(TypedDict):
    id: str
    reason_code: str
    justification: str
    origin: str
    status: str
    hedge_program_id: Optional[str]
    hedge_instrument_id: Optional[str]
    tankering_directive_id: Optional[str]
    requested_limit_value: Optional[float]
    requested_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
