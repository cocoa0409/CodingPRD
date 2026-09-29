"""TypedDict shapes for every resource the District Energy API persists.

Every resource carries an ``id`` (server-minted UUID) and a ``created_at``.
Most resources additionally carry ``updated_at`` and ``version``; the two
append-only records — DispatchOrder and MeterReading — carry only ``id`` and
``created_at``.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ─── Enumerations (as literal string sets, for readable assertions) ──────────

SERVICE_MODES = ("HEATING", "COOLING", "DUAL")
LOOP_POSTURES = ("NORMAL", "CONSTRAINED", "ISOLATED")
INSULATION_CLASSES = ("A", "B", "C")
SEGMENT_CONDITIONS = ("SOUND", "MONITORED", "SUSPECT", "UNDER_REPAIR")
FUEL_TYPES = ("NATURAL_GAS", "BIOMASS", "ELECTRICITY", "WASTE_HEAT", "FUEL_OIL")
DELIVERY_FIRMNESS = ("FIRM", "INTERRUPTIBLE")
CONTRACT_STATUSES = ("ACTIVE", "SUSPENDED", "EXPIRED")
ASSET_TYPES = ("BOILER", "CHILLER", "CHP", "BIOMASS_BOILER", "THERMAL_STORAGE")
AVAILABILITY_STATES = ("AVAILABLE", "DERATED", "OUTAGE")
OCCUPANCY_PROFILES = ("WEEKDAY_FULL", "WEEKEND_REDUCED", "HOLIDAY_MINIMAL")
FORECAST_STATES = ("DRAFT", "PUBLISHED", "SUPERSEDED")
FORECAST_VARIANTS = ("WEATHER_NORMAL_PROVISIONAL", "ACTUAL_WEIGHTED_FINAL")
PLAN_STATES = ("DRAFT", "SUBMITTED", "APPROVED", "COMMITTED", "RECONCILED", "SUPERSEDED")
CUSTOMER_CLASSES = (
    "RESIDENTIAL_MULTIFAMILY",
    "COMMERCIAL_OFFICE",
    "HOSPITAL",
    "UNIVERSITY",
    "INDUSTRIAL_PROCESS",
)
AGREEMENT_CONTRACT_STATES = ("PENDING_CAPACITY", "ACTIVE", "SUSPENDED", "TERMINATED")
AGREEMENT_BILLING_STATES = ("CURRENT", "IN_ARREARS", "WRITTEN_OFF")
METER_STATES = ("INSTALLED", "COMMISSIONED", "REMOVED")
READ_TYPES = ("ACTUAL", "ESTIMATED")
INVOICE_STATES = ("DRAFT", "ISSUED", "ADJUSTED", "PAID", "VOID")
INVOICE_VARIANTS = ("ESTIMATED", "ACTUAL_TRUE_UP")
WORK_TYPES = ("LEAK_REPAIR", "INSPECTION", "VALVE_REPLACEMENT")
WORK_STATES = (
    "DRAFT",
    "PERMIT_PENDING",
    "SCHEDULED",
    "EXCAVATING",
    "REPAIRING",
    "BACKFILLED",
    "COMPLETED",
    "CANCELLED",
)
PERMIT_DECISIONS = ("PENDING", "GRANTED", "DENIED")
PROJECT_STATES = ("SCREENING", "SIZED", "APPROVED", "REJECTED", "CONVERTED")
CLIMATE_GOAL_STATUSES = ("COMPLIANT", "EXCEEDING")


# ─── Living entities (id + created_at + updated_at + version) ───────────────


class NetworkLoop(TypedDict, total=False):
    id: str
    code: str
    name: str
    service_mode: str
    design_supply_temp_c: float
    max_pressure_kpa: float
    rated_capacity_kw: float
    posture: str
    committed_reserved_kw: float
    open_isolation_count: int
    suspect_segment_count: int
    created_at: str
    updated_at: str
    version: int


class PipeSegment(TypedDict, total=False):
    id: str
    loop_id: str
    code: str
    length_m: float
    diameter_mm: float
    install_year: int
    insulation_class: str
    buried_depth_m: float
    makeup_water_ratio: float
    historical_leak_count: int
    upstream_segment_id: Optional[str]
    condition: str
    leak_risk_score: float
    created_at: str
    updated_at: str
    version: int


class FuelSupplyContract(TypedDict, total=False):
    id: str
    supplier_code: str
    fuel_type: str
    contracted_energy_mwh_per_year: float
    price_per_mwh: float
    delivery_firmness: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionAsset(TypedDict, total=False):
    id: str
    loop_id: str
    code: str
    asset_type: str
    rated_capacity_kw: float
    marginal_cost_per_mwh: float
    emission_factor_kg_per_mwh: float
    fuel_contract_id: Optional[str]
    derated_capacity_kw: float
    min_stable_output_kw: float
    storage_capacity_kwh: float
    state_of_charge_kwh: float
    availability_state: str
    created_at: str
    updated_at: str
    version: int


class LoadForecast(TypedDict, total=False):
    id: str
    loop_id: str
    service_date: str
    occupancy_profile: str
    heating_degree_hours: float
    cooling_degree_hours: float
    actual_heating_degree_hours: Optional[float]
    actual_cooling_degree_hours: Optional[float]
    forecast_state: str
    variant_applied: Optional[str]
    coincident_demand_kw: float
    projected_energy_mwh: float
    contributing_agreement_count: int
    created_at: str
    updated_at: str
    version: int


class DispatchPlan(TypedDict, total=False):
    id: str
    loop_id: str
    forecast_id: str
    plan_state: str
    block_hours: float
    authored_by_user_id: str
    reviewed_by_user_id: Optional[str]
    allocated_capacity_kw: float
    unserved_demand_kw: float
    total_dispatch_cost: float
    total_emissions_kg: float
    reserve_margin_pct: float
    fuel_diversity_hhi: float
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    code: str
    customer_class: str
    fixed_service_charge: float
    demand_charge_per_kw: float
    minimum_bill_amount: float
    ratchet_lookback_months: int
    tiers: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class ConnectionAgreement(TypedDict, total=False):
    id: str
    loop_id: str
    rate_schedule_id: str
    customer_name: str
    customer_class: str
    reserved_capacity_kw: float
    service_mode: str
    service_start_date: str
    service_end_date: str
    contract_state: str
    billing_state: str
    billed_demand_ratchet_kw: float
    balance_due: float
    created_at: str
    updated_at: str
    version: int


class MeteringPoint(TypedDict, total=False):
    id: str
    agreement_id: str
    segment_id: str
    code: str
    multiplier: float
    meter_state: str
    last_reading_energy_mwh: float
    reading_count: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    agreement_id: str
    period_start: str
    period_end: str
    invoice_state: str
    variant_applied: str
    billed_energy_mwh: float
    billed_demand_kw: float
    load_factor_pct: float
    energy_charge: float
    demand_charge: float
    fixed_charge: float
    total_amount: float
    minimum_bill_applied: bool
    paid_amount: float
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    segment_id: str
    loop_id: str
    work_type: str
    window_start: str
    window_end: str
    requires_isolation: bool
    work_state: str
    permit_decision: str
    reported_by_user_id: str
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpansionProject(TypedDict, total=False):
    id: str
    loop_id: str
    rate_schedule_id: str
    candidate_customer_name: str
    customer_class: str
    requested_capacity_kw: float
    route_length_m: float
    assumed_annual_energy_mwh: float
    assumed_marginal_cost_per_mwh: float
    design_delta_t_c: float
    project_state: str
    selected_diameter_mm: Optional[float]
    design_flow_m3_per_h: float
    estimated_capex: float
    annual_net_margin: float
    npv: float
    created_at: str
    updated_at: str
    version: int


# ─── Append-only records (only id + created_at) ─────────────────────────────


class DispatchOrder(TypedDict, total=False):
    id: str
    plan_id: str
    asset_id: str
    merit_rank: int
    allocated_kw: float
    block_energy_mwh: float
    discharged_kwh: float
    order_cost: float
    order_emissions_kg: float
    created_at: str


class MeterReading(TypedDict, total=False):
    id: str
    point_id: str
    read_at: str
    cumulative_energy_mwh: float
    peak_demand_kw: float
    read_type: str
    multiplied_energy_mwh: float
    created_at: str


# ─── Pure computed reads ────────────────────────────────────────────────────


class EmissionsSummary(TypedDict, total=False):
    loop_id: str
    contributing_plan_count: int
    total_energy_mwh: float
    total_emissions_kg: float
    delivered_energy_mwh: float
    system_efficiency_pct: float
    emissions_intensity_kg_per_mwh: float
    target_gap_kg_per_mwh: float
    climate_goal_status: str


__all__ = [
    "SERVICE_MODES",
    "LOOP_POSTURES",
    "INSULATION_CLASSES",
    "SEGMENT_CONDITIONS",
    "FUEL_TYPES",
    "DELIVERY_FIRMNESS",
    "CONTRACT_STATUSES",
    "ASSET_TYPES",
    "AVAILABILITY_STATES",
    "OCCUPANCY_PROFILES",
    "FORECAST_STATES",
    "FORECAST_VARIANTS",
    "PLAN_STATES",
    "CUSTOMER_CLASSES",
    "AGREEMENT_CONTRACT_STATES",
    "AGREEMENT_BILLING_STATES",
    "METER_STATES",
    "READ_TYPES",
    "INVOICE_STATES",
    "INVOICE_VARIANTS",
    "WORK_TYPES",
    "WORK_STATES",
    "PERMIT_DECISIONS",
    "PROJECT_STATES",
    "CLIMATE_GOAL_STATUSES",
    "NetworkLoop",
    "PipeSegment",
    "FuelSupplyContract",
    "ProductionAsset",
    "LoadForecast",
    "DispatchPlan",
    "DispatchOrder",
    "RateSchedule",
    "ConnectionAgreement",
    "MeteringPoint",
    "MeterReading",
    "Invoice",
    "WorkOrder",
    "ExpansionProject",
    "EmissionsSummary",
]
