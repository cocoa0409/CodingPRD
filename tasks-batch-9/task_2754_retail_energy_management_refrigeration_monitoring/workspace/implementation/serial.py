"""Resource serialisation with the precision discipline of PRD section 2.8."""

from flask import g

import calc
import derive
from util import fmt_iso, q


def _eui_map():
    if not hasattr(g, "eui_map"):
        g.eui_map = calc.all_store_euis()
    return g.eui_map


def _common(row):
    return {
        "created_at": fmt_iso(row["created_at"]),
        "updated_at": fmt_iso(row["updated_at"]),
        "version": row["version"],
    }


def store(row):
    bench = calc.benchmark_for_store(row, _eui_map())
    out = {
        "id": row["id"],
        "code": row["code"],
        "climate_zone": row["climate_zone"],
        "store_format": row["store_format"],
        "floor_area_sqft": row["floor_area_sqft"],
        "blended_rate_usd_per_kwh": q(row["blended_rate_usd_per_kwh"], 4),
        "bms_status": row["bms_status"],
        "active_standard_id": row["active_standard_id"],
        "energy_posture": row["energy_posture"],
        "override_budget_kwh_month": q(row["override_budget_kwh_month"], 2),
        "override_kwh_used_month": derive.override_kwh_used_month(row["id"]),
        "verified_savings_kwh_ytd": derive.verified_savings_kwh_ytd(row["id"]),
        "portfolio_realization_rate": derive.portfolio_realization_rate(row["id"]),
        "eui_kbtu_per_sqft": bench["eui_kbtu_per_sqft"],
        "benchmark_percentile": bench["benchmark_percentile"],
        "benchmark_outlier_flag": bench["benchmark_outlier_flag"],
        "lighting_on_time_local": row["lighting_on_time_local"],
        "lighting_off_time_local": row["lighting_off_time_local"],
        "daylight_harvest_enabled": row["daylight_harvest_enabled"],
        "occupancy_control_enabled": row["occupancy_control_enabled"],
        "alarm_case_count": derive.alarm_case_count(row["id"]),
        "urgent_work_order_count": derive.urgent_work_order_count(row["id"]),
    }
    out.update(_common(row))
    return out


def standard(row):
    out = {
        "id": row["id"],
        "climate_zone": row["climate_zone"],
        "store_format": row["store_format"],
        "season": row["season"],
        "cooling_setpoint_f": q(row["cooling_setpoint_f"], 1),
        "heating_setpoint_f": q(row["heating_setpoint_f"], 1),
        "deadband_f": q(row["deadband_f"], 1),
        "lighting_lux_target": row["lighting_lux_target"],
        "status": row["status"],
        "revision": row["revision"],
        "supersedes_standard_id": row["supersedes_standard_id"],
        "published_at_iso": fmt_iso(row["published_at_iso"]),
        "published_by_user_id": row["published_by_user_id"],
    }
    out.update(_common(row))
    return out


def account(row):
    out = {
        "id": row["id"],
        "store_id": row["store_id"],
        "utility_name": row["utility_name"],
        "rate_schedule_code": row["rate_schedule_code"],
        "rate_family": row["rate_family"],
        "demand_charge_per_kw": q(row["demand_charge_per_kw"], 2),
        "rate_on_peak": q(row["rate_on_peak"], 4),
        "rate_off_peak": q(row["rate_off_peak"], 4),
        "ratchet_peak_kw": q(row["ratchet_peak_kw"], 1),
        "candidate_rate_schedule_code": row["candidate_rate_schedule_code"],
        "candidate_rate_family": row["candidate_rate_family"],
        "candidate_demand_charge_per_kw": q(row["candidate_demand_charge_per_kw"], 2),
        "candidate_rate_on_peak": q(row["candidate_rate_on_peak"], 4),
        "candidate_rate_off_peak": q(row["candidate_rate_off_peak"], 4),
        "tariff_state": row["tariff_state"],
        "tariff_switch_effective_from_iso": fmt_iso(row["tariff_switch_effective_from_iso"]),
        "tariff_locked_until_iso": fmt_iso(row["tariff_locked_until_iso"]),
        "dr_enrollment_state": row["dr_enrollment_state"],
        "dr_optout_count": derive.dr_optout_count(row["id"]),
        "dr_incentive_accrued_usd": derive.dr_incentive_accrued_usd(row["id"]),
    }
    out.update(_common(row))
    return out


def bill(row):
    out = {
        "id": row["id"],
        "utility_account_id": row["utility_account_id"],
        "period_start_iso": fmt_iso(row["period_start_iso"]),
        "period_end_iso": fmt_iso(row["period_end_iso"]),
        "on_peak_kwh": q(row["on_peak_kwh"], 2),
        "off_peak_kwh": q(row["off_peak_kwh"], 2),
        "billed_kwh": q(row["billed_kwh"], 2),
        "billed_peak_kw": q(row["billed_peak_kw"], 1),
        "billed_amount_usd": q(row["billed_amount_usd"], 2),
        "recomputed_energy_cost_usd": q(row["recomputed_energy_cost_usd"], 2),
        "recomputed_demand_cost_usd": q(row["recomputed_demand_cost_usd"], 2),
        "recomputed_rider_cost_usd": q(row["recomputed_rider_cost_usd"], 2),
        "recomputed_surcharge_usd": q(row["recomputed_surcharge_usd"], 2),
        "recomputed_amount_usd": q(row["recomputed_amount_usd"], 2),
        "billable_demand_kw": q(row["billable_demand_kw"], 1),
        "peak_basis": row["peak_basis"],
        "variance_pct": q(row["variance_pct"], 2),
        "validation_state": row["validation_state"],
        "recomputed_by_user_id": row["recomputed_by_user_id"],
        "dispute_reason": row["dispute_reason"],
        "adjusted_amount_usd": q(row["adjusted_amount_usd"], 2),
        "adjusted_by_user_id": row["adjusted_by_user_id"],
    }
    out.update(_common(row))
    return out


def interval(row):
    return {
        "id": row["id"],
        "utility_account_id": row["utility_account_id"],
        "interval_start_iso": fmt_iso(row["interval_start_iso"]),
        "kw_demand": q(row["kw_demand"], 1),
        "is_on_peak": row["is_on_peak"],
        "is_dr_event_day": row["is_dr_event_day"],
        "created_at": fmt_iso(row["created_at"]),
    }


def dr_event(row):
    out = {
        "id": row["id"],
        "utility_account_id": row["utility_account_id"],
        "program_code": row["program_code"],
        "curtailment_start_iso": fmt_iso(row["curtailment_start_iso"]),
        "curtailment_end_iso": fmt_iso(row["curtailment_end_iso"]),
        "target_reduction_kw": q(row["target_reduction_kw"], 1),
        "baseline_kw": q(row["baseline_kw"], 2),
        "total_reduction_kwh": q(row["total_reduction_kwh"], 2),
        "performance_pct": q(row["performance_pct"], 1),
        "incentive_usd": q(row["incentive_usd"], 2),
        "penalty_usd": q(row["penalty_usd"], 2),
        "event_state": row["event_state"],
        "settlement_state": row["settlement_state"],
        "notified_at_iso": fmt_iso(row["notified_at_iso"]),
        "opt_out_reason": row["opt_out_reason"],
        "reversal_reason": row["reversal_reason"],
    }
    out.update(_common(row))
    return out


def case(row):
    out = {
        "id": row["id"],
        "store_id": row["store_id"],
        "case_code": row["case_code"],
        "case_type": row["case_type"],
        "product_class": row["product_class"],
        "alarm_high_f": q(row["alarm_high_f"], 1),
        "alarm_low_f": q(row["alarm_low_f"], 1),
        "product_value_usd": q(row["product_value_usd"], 2),
        "monitoring_state": row["monitoring_state"],
        "consecutive_breach_count": row["consecutive_breach_count"],
        "last_reading_temp_f": q(row["last_reading_temp_f"], 1),
        "last_reading_iso": fmt_iso(row["last_reading_iso"]),
    }
    out.update(_common(row))
    return out


def excursion(row):
    out = {
        "id": row["id"],
        "case_id": row["case_id"],
        "first_breach_iso": fmt_iso(row["first_breach_iso"]),
        "last_breach_iso": fmt_iso(row["last_breach_iso"]),
        "peak_temp_f": q(row["peak_temp_f"], 1),
        "exposure_minutes": row["exposure_minutes"],
        "state": row["state"],
        "product_value_usd": q(row["product_value_usd"], 2),
        "mandatory_disposition": row["mandatory_disposition"],
        "acknowledged_by_user_id": row["acknowledged_by_user_id"],
        "disposition": row["disposition"],
        "corrective_action_note": row["corrective_action_note"],
        "documented_by_user_id": row["documented_by_user_id"],
        "documented_at_iso": fmt_iso(row["documented_at_iso"]),
        "closed_at_iso": fmt_iso(row["closed_at_iso"]),
    }
    out.update(_common(row))
    return out


def override(row):
    out = {
        "id": row["id"],
        "store_id": row["store_id"],
        "zone": row["zone"],
        "override_type": row["override_type"],
        "start_iso": fmt_iso(row["start_iso"]),
        "end_iso": fmt_iso(row["end_iso"]),
        "zone_load_kw": q(row["zone_load_kw"], 1),
        "projected_kwh": q(row["projected_kwh"], 2),
        "state": row["state"],
        "requested_reason": row["requested_reason"],
        "revoked_by_user_id": row["revoked_by_user_id"],
        "revoke_source": row["revoke_source"],
    }
    out.update(_common(row))
    return out


def fault(row):
    out = {
        "id": row["id"],
        "store_id": row["store_id"],
        "equipment_ref": row["equipment_ref"],
        "equipment_class": row["equipment_class"],
        "fault_code": row["fault_code"],
        "severity": row["severity"],
        "occurrence_count": row["occurrence_count"],
        "affected_load_kw": q(row["affected_load_kw"], 1),
        "fault_score": q(row["fault_score"], 1),
        "state": row["state"],
        "detected_at_iso": fmt_iso(row["detected_at_iso"]),
        "triaged_by_user_id": row["triaged_by_user_id"],
    }
    out.update(_common(row))
    return out


def work_order(row):
    out = {
        "id": row["id"],
        "fault_id": row["fault_id"],
        "priority": row["priority"],
        "state": row["state"],
        "scheduled_start_iso": fmt_iso(row["scheduled_start_iso"]),
        "scheduled_end_iso": fmt_iso(row["scheduled_end_iso"]),
        "completed_at_iso": fmt_iso(row["completed_at_iso"]),
        "completion_note": row["completion_note"],
    }
    out.update(_common(row))
    return out


def retrofit(row):
    out = {
        "id": row["id"],
        "store_id": row["store_id"],
        "measure_type": row["measure_type"],
        "capex_usd": q(row["capex_usd"], 2),
        "projected_annual_savings_kwh": q(row["projected_annual_savings_kwh"], 2),
        "annual_savings_usd": q(row["annual_savings_usd"], 2),
        "payback_years": q(row["payback_years"], 2),
        "priority_score": q(row["priority_score"], 1),
        "priority_basis": row["priority_basis"],
        "state": row["state"],
        "escalated_review": row["escalated_review"],
        "proposed_by_user_id": row["proposed_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "install_completed_iso": fmt_iso(row["install_completed_iso"]),
        "baseline_period_kwh": q(row["baseline_period_kwh"], 2),
        "post_period_kwh": q(row["post_period_kwh"], 2),
        "mv_period_days": row["mv_period_days"],
        "adjusted_baseline_kwh": q(row["adjusted_baseline_kwh"], 2),
        "measured_savings_kwh": q(row["measured_savings_kwh"], 2),
        "realization_rate": q(row["realization_rate"], 4),
        "revocation_reason": row["revocation_reason"],
    }
    out.update(_common(row))
    return out
