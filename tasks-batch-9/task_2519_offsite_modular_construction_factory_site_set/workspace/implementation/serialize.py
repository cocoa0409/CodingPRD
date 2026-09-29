"""Entity serialisers — the field set of §1.1 plus the four common properties."""

from decimal import Decimal

from store import fmt_dt


def _n(value):
    """Numbers leave as JSON numbers; Decimals become plain floats."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def factory(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "code": row["code"],
            "takt_minutes": row["takt_minutes"],
            "station_count": row["station_count"],
            "parallel_station_capacity": row["parallel_station_capacity"],
            "wip_unit_value_cents": row["wip_unit_value_cents"],
            "shift_start_minute_of_day": row["shift_start_minute_of_day"],
            "shift_minutes_per_day": row["shift_minutes_per_day"],
            "line_state": row["line_state"],
            "committed_line_minutes": row["committed_line_minutes"],
        }
    )
    return out


def agency(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "agency_code": row["agency_code"],
            "accreditation_state": row["accreditation_state"],
            "accredited_state_codes": list(row["accredited_state_codes"]),
            "per_inspection_fee_cents": row["per_inspection_fee_cents"],
            "hold_authority": row["hold_authority"],
        }
    )
    return out


def project(row):
    out = _common(row)
    out.update(
        {
            "name": row["name"],
            "factory_id": row["factory_id"],
            "state_code": row["state_code"],
            "ahj_code": row["ahj_code"],
            "planned_module_count": row["planned_module_count"],
            "contract_price_cents": row["contract_price_cents"],
            "deposit_pct": _n(row["deposit_pct"]),
            "retainage_pct": _n(row["retainage_pct"]),
            "crane_capacity_chart": [dict(e) for e in row["crane_capacity_chart"]],
            "crane_rigging_buffer_minutes": row["crane_rigging_buffer_minutes"],
            "set_sequence_policy": row["set_sequence_policy"],
            "weather_exposure_limit_hours": _n(row["weather_exposure_limit_hours"]),
            "forecast_precip_probability_pct": _n(row["forecast_precip_probability_pct"]),
            "forecast_wind_gust_mph": _n(row["forecast_wind_gust_mph"]),
            "last_weather_observed_at": fmt_dt(row["last_weather_observed_at"]),
            "permit_posture": row["permit_posture"],
            "phase": row["phase"],
            "wip_certified_cents": row["wip_certified_cents"],
            "funded_to_date_cents": row["funded_to_date_cents"],
            "modules_set_count": row["modules_set_count"],
            "modules_connected_count": row["modules_connected_count"],
        }
    )
    return out


def design_package(row):
    out = _common(row)
    out.update(
        {
            "project_id": row["project_id"],
            "revision_index": row["revision_index"],
            "supersedes_package_id": row["supersedes_package_id"],
            "freeze_state": row["freeze_state"],
            "revision_round": row["revision_round"],
            "module_split_count": row["module_split_count"],
            "connection_detail_state": row["connection_detail_state"],
            "open_connection_conflicts": row["open_connection_conflicts"],
            "field_scope_items_open": row["field_scope_items_open"],
            "factory_compatibility_score": _n(row["factory_compatibility_score"]),
            "submitted_by_user_id": row["submitted_by_user_id"],
            "reviewed_by_user_id": row["reviewed_by_user_id"],
            "review_note": row["review_note"],
        }
    )
    return out


def module(row):
    out = _common(row)
    out.update(
        {
            "project_id": row["project_id"],
            "design_package_id": row["design_package_id"],
            "shipment_id": row["shipment_id"],
            "module_code": row["module_code"],
            "pair_role": row["pair_role"],
            "pair_group_code": row["pair_group_code"],
            "set_sequence_index": row["set_sequence_index"],
            "width_in": row["width_in"],
            "length_in": row["length_in"],
            "height_in": row["height_in"],
            "gross_weight_lb": row["gross_weight_lb"],
            "envelope_class": row["envelope_class"],
            "production_status": row["production_status"],
            "qc_status": row["qc_status"],
            "site_status": row["site_status"],
            "station_index": row["station_index"],
            "line_slot_start": fmt_dt(row["line_slot_start"]),
            "line_slot_end": fmt_dt(row["line_slot_end"]),
            "line_slot_minutes": row["line_slot_minutes"],
            "pick_window_start": fmt_dt(row["pick_window_start"]),
            "pick_window_end": fmt_dt(row["pick_window_end"]),
            "pick_radius_ft": row["pick_radius_ft"],
            "rigging_weight_lb": row["rigging_weight_lb"],
            "crane_utilization_pct": _n(row["crane_utilization_pct"]),
            "connection_scope_owner": row["connection_scope_owner"],
            "set_at": fmt_dt(row["set_at"]),
            "connected_at": fmt_dt(row["connected_at"]),
            "exposure_open_hours": _n(row["exposure_open_hours"]),
            "wip_earned_cents": row["wip_earned_cents"],
            "defect_count_factory": row["defect_count_factory"],
            "defect_count_field": row["defect_count_field"],
        }
    )
    return out


def permit(row):
    out = _common(row)
    out.update(
        {
            "project_id": row["project_id"],
            "track": row["track"],
            "scope": row["scope"],
            "status": row["status"],
            "pinned_package_id": row["pinned_package_id"],
            "conditions_count": row["conditions_count"],
            "insignia_count_issued": row["insignia_count_issued"],
            "decided_at": fmt_dt(row["decided_at"]),
            "decided_by_user_id": row["decided_by_user_id"],
            "expires_at": fmt_dt(row["expires_at"]),
        }
    )
    return out


def inspection(row):
    out = _common(row)
    out.update(
        {
            "module_id": row["module_id"],
            "agency_id": row["agency_id"],
            "stage": row["stage"],
            "result": row["result"],
            "defect_count": row["defect_count"],
            "severity_max": row["severity_max"],
            "hold_state": row["hold_state"],
            "corrective_note": row["corrective_note"],
            "recorded_at": fmt_dt(row["recorded_at"]),
            "recorded_by_user_id": row["recorded_by_user_id"],
        }
    )
    return out


def shipment(row):
    out = _common(row)
    out.update(
        {
            "project_id": row["project_id"],
            "carrier_code": row["carrier_code"],
            "route_state_codes": list(row["route_state_codes"]),
            "planned_departure_at": fmt_dt(row["planned_departure_at"]),
            "planned_arrival_at": fmt_dt(row["planned_arrival_at"]),
            "status": row["status"],
            "route_survey_state": row["route_survey_state"],
            "survey_completed_at": fmt_dt(row["survey_completed_at"]),
            "escort_required": row["escort_required"],
            "escort_confirmed": row["escort_confirmed"],
            "permit_expires_at": fmt_dt(row["permit_expires_at"]),
            "permit_fee_cents": row["permit_fee_cents"],
            "loaded_module_count": row["loaded_module_count"],
            "max_envelope_class": row["max_envelope_class"],
            "dispatched_at": fmt_dt(row["dispatched_at"]),
            "delivered_at": fmt_dt(row["delivered_at"]),
            "cancel_reason": row["cancel_reason"],
        }
    )
    return out


def defect_claim(row):
    out = _common(row)
    out.update(
        {
            "module_id": row["module_id"],
            "inspection_id": row["inspection_id"],
            "discovered_phase": row["discovered_phase"],
            "description": row["description"],
            "repair_cost_cents": row["repair_cost_cents"],
            "responsibility": row["responsibility"],
            "factory_share_pct": _n(row["factory_share_pct"]),
            "field_share_pct": _n(row["field_share_pct"]),
            "factory_charge_cents": row["factory_charge_cents"],
            "field_charge_cents": row["field_charge_cents"],
            "warranty_bucket": row["warranty_bucket"],
            "status": row["status"],
            "adjudication_round": row["adjudication_round"],
            "adjudicated_by_user_id": row["adjudicated_by_user_id"],
            "dispute_note": row["dispute_note"],
        }
    )
    return out


def draw(row):
    out = _common(row)
    out.update(
        {
            "project_id": row["project_id"],
            "draw_index": row["draw_index"],
            "basis_mode": row["basis_mode"],
            "certifying_agency_id": row["certifying_agency_id"],
            "basis_module_count": row["basis_module_count"],
            "basis_earned_cents": row["basis_earned_cents"],
            "requested_cents": row["requested_cents"],
            "certified_basis_cents": row["certified_basis_cents"],
            "certified_cents": row["certified_cents"],
            "retainage_held_cents": row["retainage_held_cents"],
            "net_funded_cents": row["net_funded_cents"],
            "status": row["status"],
            "certified_at": fmt_dt(row["certified_at"]),
            "funded_at": fmt_dt(row["funded_at"]),
            "reject_reason": row["reject_reason"],
        }
    )
    return out
