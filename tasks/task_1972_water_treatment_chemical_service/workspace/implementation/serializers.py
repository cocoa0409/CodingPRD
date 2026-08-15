"""Entity -> JSON dict serializers. Field sets follow the scaffold entity
table exactly. Common resources carry id/created_at/updated_at/version; the
thin append-only records (TelemetryReading, WaterTestResult, BlowdownEvent)
carry only id/created_at."""

from db import fmt_ts, fmt_ts_seconds


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def _thin(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
    }


def account(e):
    out = _common(e)
    out.update({
        "account_name": e["account_name"],
        "credit_hold": e["credit_hold"],
        "billing_model": e["billing_model"],
        "open_balance_cents": e["open_balance_cents"],
        "status": e["status"],
    })
    return out


def asset(e):
    out = _common(e)
    out.update({
        "account_id": e["account_id"],
        "asset_tag": e["asset_tag"],
        "asset_type": e["asset_type"],
        "recirculation_rate_gpm": e["recirculation_rate_gpm"],
        "system_volume_gal": e["system_volume_gal"],
        "metallurgy": e["metallurgy"],
        "evaporation_factor": e["evaporation_factor"],
        "drift_factor": e["drift_factor"],
        "target_coc": e["target_coc"],
        "consecutive_out_of_range_count": e["consecutive_out_of_range_count"],
        "posture": e["posture"],
        "status": e["status"],
    })
    return out


def program_design(e):
    out = _common(e)
    out.update({
        "asset_id": e["asset_id"],
        "survey_notes": e["survey_notes"],
        "proposed_coc": e["proposed_coc"],
        "inhibitor_target_ppm": e["inhibitor_target_ppm"],
        "ph_min": e["ph_min"],
        "ph_max": e["ph_max"],
        "conductivity_max_umhos": e["conductivity_max_umhos"],
        "service_rate_cents_per_month": e["service_rate_cents_per_month"],
        "revision_number": e["revision_number"],
        "status": e["status"],
    })
    return out


def product(e):
    out = _common(e)
    out.update({
        "product_code": e["product_code"],
        "active_pct": e["active_pct"],
        "container_size_gal": e["container_size_gal"],
        "unit_price_cents_per_gal": e["unit_price_cents_per_gal"],
        "contract_price_cents_per_gal": e["contract_price_cents_per_gal"],
        "density_g_per_ml": e["density_g_per_ml"],
        "status": e["status"],
    })
    return out


def feed_station(e):
    out = _common(e)
    out.update({
        "asset_id": e["asset_id"],
        "product_id": e["product_id"],
        "feed_mode": e["feed_mode"],
        "capacity_cap_ml_per_min": e["capacity_cap_ml_per_min"],
        "setpoint_ml_per_min": e["setpoint_ml_per_min"],
        "inventory_gal": e["inventory_gal"],
        "consumption_rate_gal_per_day": e["consumption_rate_gal_per_day"],
        "projected_depletion_at": fmt_ts_seconds(e["projected_depletion_at"]),
        "last_telemetry_at": fmt_ts(e["last_telemetry_at"]),
        "status": e["status"],
    })
    return out


def telemetry_reading(e):
    out = _thin(e)
    out.update({
        "station_id": e["station_id"],
        "recorded_at": fmt_ts(e["recorded_at"]),
        "feed_pulses": e["feed_pulses"],
        "ml_per_pulse": e["ml_per_pulse"],
        "level_gal": e["level_gal"],
    })
    return out


def test_route(e):
    out = _common(e)
    out.update({
        "account_id": e["account_id"],
        "route_name": e["route_name"],
        "status": e["status"],
    })
    return out


def route_stop(e):
    out = _common(e)
    out.update({
        "route_id": e["route_id"],
        "asset_id": e["asset_id"],
        "window_start": fmt_ts(e["window_start"]),
        "window_end": fmt_ts(e["window_end"]),
        "sequence_index": e["sequence_index"],
        "status": e["status"],
    })
    return out


def water_test_result(e):
    out = _thin(e)
    out.update({
        "stop_id": e["stop_id"],
        "asset_id": e["asset_id"],
        "ph": e["ph"],
        "conductivity_umhos": e["conductivity_umhos"],
        "calcium_ppm": e["calcium_ppm"],
        "alkalinity_ppm": e["alkalinity_ppm"],
        "temperature_f": e["temperature_f"],
        "inhibitor_residual_ppm": e["inhibitor_residual_ppm"],
        "lab_tds_ppm": e["lab_tds_ppm"],
        "lsi_provisional": e["lsi_provisional"],
        "lsi_final": e["lsi_final"],
        "classification": e["classification"],
        "range_status": e["range_status"],
        "status": e["status"],
    })
    return out


def corrective_action(e):
    out = _common(e)
    out.update({
        "asset_id": e["asset_id"],
        "triggering_result_id": e["triggering_result_id"],
        "recorded_by_user_id": e["recorded_by_user_id"],
        "setpoint_delta_ml_per_min": e["setpoint_delta_ml_per_min"],
        "rationale": e["rationale"],
        "status": e["status"],
    })
    return out


def coupon_rack(e):
    out = _common(e)
    out.update({
        "asset_id": e["asset_id"],
        "rack_code": e["rack_code"],
        "position_count": e["position_count"],
        "status": e["status"],
    })
    return out


def corrosion_coupon(e):
    out = _common(e)
    out.update({
        "rack_id": e["rack_id"],
        "position_index": e["position_index"],
        "alloy": e["alloy"],
        "density_g_cm3": e["density_g_cm3"],
        "area_in2": e["area_in2"],
        "pre_weight_g": e["pre_weight_g"],
        "installed_at": fmt_ts(e["installed_at"]),
        "removed_at": fmt_ts_seconds(e["removed_at"]),
        "post_weight_g": e["post_weight_g"],
        "exposure_days": e["exposure_days"],
        "corrosion_rate_mpy": e["corrosion_rate_mpy"],
        "rating": e["rating"],
        "status": e["status"],
    })
    return out


def legionella_plan(e):
    out = _common(e)
    out.update({
        "asset_id": e["asset_id"],
        "plan_text": e["plan_text"],
        "validation_interval_days": e["validation_interval_days"],
        "last_validated_at": fmt_ts(e["last_validated_at"]),
        "validation_due_at": fmt_ts_seconds(e["validation_due_at"]),
        "status": e["status"],
    })
    return out


def blowdown_event(e):
    out = _thin(e)
    out.update({
        "asset_id": e["asset_id"],
        "occurred_at": fmt_ts(e["occurred_at"]),
        "blowdown_gal": e["blowdown_gal"],
        "makeup_gal": e["makeup_gal"],
        "evaporation_gal": e["evaporation_gal"],
        "balance_residual_gal": e["balance_residual_gal"],
    })
    return out


def delivery_order(e):
    out = _common(e)
    out.update({
        "account_id": e["account_id"],
        "station_id": e["station_id"],
        "quantity_gal": e["quantity_gal"],
        "scheduled_for": fmt_ts(e["scheduled_for"]),
        "delivered_gal": e["delivered_gal"],
        "returned_residual_gal": e["returned_residual_gal"],
        "auto_drafted": e["auto_drafted"],
        "status": e["status"],
    })
    return out


def invoice(e):
    out = _common(e)
    out.update({
        "account_id": e["account_id"],
        "period_start": fmt_ts(e["period_start"]),
        "period_end": fmt_ts(e["period_end"]),
        "pricing_variant": e["pricing_variant"],
        "product_charges_cents": e["product_charges_cents"],
        "service_fee_cents": e["service_fee_cents"],
        "invoice_total_cents": e["invoice_total_cents"],
        "status": e["status"],
    })
    return out
