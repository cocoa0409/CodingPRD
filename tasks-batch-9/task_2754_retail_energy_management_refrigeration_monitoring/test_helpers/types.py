"""Data structures mirroring the resources described by the PRD.

Every resource except DemandInterval carries the common identity block of
id, created_at, updated_at and version. A demand interval is an append-only
event row and carries only id and created_at.
"""
from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Store(CommonFields):
    code: str
    climate_zone: str
    store_format: str
    floor_area_sqft: int
    blended_rate_usd_per_kwh: float
    override_budget_kwh_month: float
    lighting_on_time_local: str
    lighting_off_time_local: str
    daylight_harvest_enabled: bool
    occupancy_control_enabled: bool
    bms_status: str
    active_standard_id: Optional[str]
    energy_posture: str
    override_kwh_used_month: float
    verified_savings_kwh_ytd: float
    portfolio_realization_rate: float
    alarm_case_count: int
    urgent_work_order_count: int
    eui_kbtu_per_sqft: Optional[float]
    benchmark_percentile: Optional[float]
    benchmark_outlier_flag: bool


class SetpointStandard(CommonFields):
    climate_zone: str
    store_format: str
    season: str
    cooling_setpoint_f: float
    heating_setpoint_f: float
    deadband_f: float
    lighting_lux_target: int
    status: str
    revision: int
    supersedes_standard_id: Optional[str]
    published_at_iso: Optional[str]
    published_by_user_id: Optional[str]


class UtilityAccount(CommonFields):
    store_id: str
    utility_name: str
    rate_schedule_code: str
    rate_family: str
    demand_charge_per_kw: float
    rate_on_peak: float
    rate_off_peak: float
    ratchet_peak_kw: float
    candidate_rate_schedule_code: Optional[str]
    candidate_rate_family: Optional[str]
    candidate_demand_charge_per_kw: Optional[float]
    candidate_rate_on_peak: Optional[float]
    candidate_rate_off_peak: Optional[float]
    tariff_state: str
    tariff_switch_effective_from_iso: Optional[str]
    tariff_locked_until_iso: Optional[str]
    dr_enrollment_state: str
    dr_optout_count: int
    dr_incentive_accrued_usd: float


class DemandInterval(TypedDict):
    """Append-only event row: id and created_at only."""
    id: str
    created_at: str
    utility_account_id: str
    interval_start_iso: str
    kw_demand: float
    is_on_peak: bool
    is_dr_event_day: bool


class UtilityBill(CommonFields):
    utility_account_id: str
    period_start_iso: str
    period_end_iso: str
    on_peak_kwh: float
    off_peak_kwh: float
    billed_kwh: float
    billed_peak_kw: float
    billed_amount_usd: float
    validation_state: str
    recomputed_energy_cost_usd: Optional[float]
    recomputed_demand_cost_usd: Optional[float]
    recomputed_rider_cost_usd: Optional[float]
    recomputed_surcharge_usd: Optional[float]
    recomputed_amount_usd: Optional[float]
    billable_demand_kw: Optional[float]
    peak_basis: Optional[str]
    variance_pct: Optional[float]
    recomputed_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    adjusted_amount_usd: Optional[float]
    adjusted_by_user_id: Optional[str]


class DemandResponseEvent(CommonFields):
    utility_account_id: str
    program_code: str
    curtailment_start_iso: str
    curtailment_end_iso: str
    target_reduction_kw: float
    event_state: str
    settlement_state: str
    baseline_kw: Optional[float]
    notified_at_iso: Optional[str]
    total_reduction_kwh: Optional[float]
    performance_pct: Optional[float]
    incentive_usd: float
    penalty_usd: float
    opt_out_reason: Optional[str]
    reversal_reason: Optional[str]


class RefrigerationCase(CommonFields):
    store_id: str
    case_code: str
    case_type: str
    product_class: str
    alarm_high_f: float
    alarm_low_f: float
    product_value_usd: float
    monitoring_state: str
    consecutive_breach_count: int
    last_reading_temp_f: Optional[float]
    last_reading_iso: Optional[str]


class TempExcursion(CommonFields):
    case_id: str
    state: str
    first_breach_iso: str
    last_breach_iso: str
    exposure_minutes: int
    peak_temp_f: float
    product_value_usd: float
    mandatory_disposition: str
    acknowledged_by_user_id: Optional[str]
    disposition: Optional[str]
    corrective_action_note: Optional[str]
    documented_by_user_id: Optional[str]
    documented_at_iso: Optional[str]
    closed_at_iso: Optional[str]


class LightingOverride(CommonFields):
    store_id: str
    zone: str
    override_type: str
    start_iso: str
    end_iso: str
    zone_load_kw: float
    requested_reason: str
    projected_kwh: float
    state: str
    revoke_source: Optional[str]
    revoked_by_user_id: Optional[str]


class FaultDiagnostic(CommonFields):
    store_id: str
    equipment_ref: str
    equipment_class: str
    fault_code: str
    severity: str
    occurrence_count: int
    affected_load_kw: float
    fault_score: float
    state: str
    detected_at_iso: str
    triaged_by_user_id: Optional[str]


class MaintenanceWorkOrder(CommonFields):
    fault_id: str
    priority: str
    state: str
    scheduled_start_iso: Optional[str]
    scheduled_end_iso: Optional[str]
    completed_at_iso: Optional[str]
    completion_note: Optional[str]


class CapitalRetrofitProject(CommonFields):
    store_id: str
    measure_type: str
    capex_usd: float
    projected_annual_savings_kwh: float
    annual_savings_usd: float
    payback_years: float
    priority_score: float
    priority_basis: str
    state: str
    escalated_review: bool
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    install_completed_iso: Optional[str]
    baseline_period_kwh: Optional[float]
    post_period_kwh: Optional[float]
    mv_period_days: Optional[int]
    adjusted_baseline_kwh: Optional[float]
    measured_savings_kwh: Optional[float]
    realization_rate: Optional[float]
    revocation_reason: Optional[str]


COMMON_FIELD_NAMES = ["id", "created_at", "updated_at", "version"]
EVENT_ROW_FIELD_NAMES = ["id", "created_at"]
