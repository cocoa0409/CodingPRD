"""Resource serialisation. Derived fields are computed at read time."""
import derive


def _dt(row, name):
    """Echo a client-supplied instant verbatim; render server instants as ISO-ms."""
    raw = row.get("_raw", {})
    if name in raw:
        return raw[name]
    return row.get(name)


def _common(row, out):
    out["created_at"] = row["created_at"]
    if "version" in row:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


# --------------------------------------------------------------------------
def funding_agreement(row):
    out = {
        "id": row["id"],
        "agreement_code": row["agreement_code"],
        "funder_name": row["funder_name"],
        "min_uptime_pct": row["min_uptime_pct"],
        "penalty_per_point_cents": row["penalty_per_point_cents"],
        "initial_holdback_cents": row["initial_holdback_cents"],
        "holdback_balance_cents": derive.holdback_balance_cents(row),
        "uptime_method": row["uptime_method"],
    }
    return _common(row, out)


def station(row):
    station_id = row["id"]
    rollup = derive.metering_rollup(station_id)
    out = {
        "id": station_id,
        "funding_agreement_id": row["funding_agreement_id"],
        "code": row["code"],
        "name": row["name"],
        "nozzle_count": row["nozzle_count"],
        "offload_bay_count": row["offload_bay_count"],
        "storage_capacity_kg": row["storage_capacity_kg"],
        "reserve_floor_kg": row["reserve_floor_kg"],
        "max_pressure_class": row["max_pressure_class"],
        "setback_compliant": row["setback_compliant"],
        "ventilation_status": row["ventilation_status"],
        "leak_detection_status": row["leak_detection_status"],
        "compressor_status": row["compressor_status"],
        "safety_posture": derive.safety_posture(row),
        "onsite_inventory_kg": derive.onsite_inventory(station_id),
        "reserved_kg": derive.reserved_kg(station_id),
        "available_kg": derive.available_kg(station_id),
        "total_deliverable_kg": derive.total_deliverable_kg(station_id),
        "high_bank_deliverable_kg": derive.total_deliverable_kg(station_id, high_only=True),
        "inbound_planned_kg": derive.inbound_planned_kg(station_id),
        "projected_available_kg": derive.projected_available_kg(station_id),
        "supply_alert": derive.supply_alert(row),
        "metered_kg_mtd": rollup["metered_kg_mtd"],
        "corrected_kg_mtd": rollup["corrected_kg_mtd"],
        "metering_error_pct_mtd": rollup["metering_error_pct_mtd"],
        "metering_accuracy_flag": rollup["metering_accuracy_flag"],
        "credits_issued_total_mt": derive.credits_issued_total_mt(station_id),
    }
    return _common(row, out)


def pressure_vessel(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "bank_tier": row["bank_tier"],
        "water_volume_l": row["water_volume_l"],
        "mawp_bar": row["mawp_bar"],
        "min_residual_bar": row["min_residual_bar"],
        "initial_pressure_bar": row["initial_pressure_bar"],
        "current_pressure_bar": row["current_pressure_bar"],
        "stored_mass_kg": derive.vessel_stored_mass(row),
        "last_inspection_date": row["last_inspection_date"],
        "next_inspection_due_date": row["next_inspection_due_date"],
        "inspection_status": derive.vessel_status(row),
        "inspection_count": row["inspection_count"],
    }
    return _common(row, out)


def production_asset(row):
    out = {
        "id": row["id"],
        "asset_code": row["asset_code"],
        "pathway": row["pathway"],
        "nameplate_kg_per_day": row["nameplate_kg_per_day"],
        "ccs_capture_rate": row["ccs_capture_rate"],
        "operator_org": row["operator_org"],
    }
    return _common(row, out)


def power_contract(row):
    out = {
        "id": row["id"],
        "production_asset_id": row["production_asset_id"],
        "contract_code": row["contract_code"],
        "grid_ci_gco2e_per_mwh": row["grid_ci_gco2e_per_mwh"],
        "annual_renewable_pct": row["annual_renewable_pct"],
        "hourly_matched_renewable_pct": row["hourly_matched_renewable_pct"],
        "hourly_matching_enabled": row["hourly_matching_enabled"],
        "effective_from": _dt(row, "effective_from"),
        "effective_to": _dt(row, "effective_to"),
    }
    return _common(row, out)


def production_lot(row):
    out = {
        "id": row["id"],
        "production_asset_id": row["production_asset_id"],
        "predecessor_lot_id": row["predecessor_lot_id"],
        "lot_code": row["lot_code"],
        "mass_kg": row["mass_kg"],
        "energy_consumed_kwh": row["energy_consumed_kwh"],
        "feedstock_consumed_mmbtu": row["feedstock_consumed_mmbtu"],
        "carryover_kg": row["carryover_kg"],
        "production_start_at": _dt(row, "production_start_at"),
        "production_end_at": _dt(row, "production_end_at"),
        "selected_power_contract_id": row["selected_power_contract_id"],
        "ci_provisional_gco2e_per_mj": row["ci_provisional_gco2e_per_mj"],
        "ci_certified_gco2e_per_mj": row["ci_certified_gco2e_per_mj"],
        "ci_variant_applied": row["ci_variant_applied"],
        "qa_status": row["qa_status"],
        "ci_status": row["ci_status"],
        "status": row["status"],
        "released_by_user_id": row["released_by_user_id"],
        "accepted_delivered_kg": derive.accepted_delivered_kg(row["id"]),
    }
    return _common(row, out)


def purity_test(row):
    out = {
        "id": row["id"],
        "production_lot_id": row["production_lot_id"],
        "performed_by_user_id": row["performed_by_user_id"],
        "sampled_at": _dt(row, "sampled_at"),
        "total_hydrocarbons_ppm": row["total_hydrocarbons_ppm"],
        "water_ppm": row["water_ppm"],
        "oxygen_ppm": row["oxygen_ppm"],
        "nitrogen_ppm": row["nitrogen_ppm"],
        "carbon_monoxide_ppm": row["carbon_monoxide_ppm"],
        "carbon_dioxide_ppm": row["carbon_dioxide_ppm"],
        "total_sulfur_ppm": row["total_sulfur_ppm"],
        "ammonia_ppm": row["ammonia_ppm"],
        "helium_ppm": row["helium_ppm"],
        "verdict": row["verdict"],
        "failing_analytes": list(row["failing_analytes"]),
        "purity_margin_pct": row["purity_margin_pct"],
        "created_at": row["created_at"],
    }
    return out


def ledger_entry(row, resulting_kg):
    return {
        "id": row["id"],
        "station_id": row["station_id"],
        "sequence_no": row["sequence_no"],
        "reason": row["reason"],
        "delta_kg": row["delta_kg"],
        "resulting_onsite_kg": resulting_kg,
        "source_ref_type": row["source_ref_type"],
        "source_ref_id": row["source_ref_id"],
        "occurred_at": row["occurred_at"],
        "created_at": row["created_at"],
    }


def delivery(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "production_lot_id": row["production_lot_id"],
        "receiving_vessel_id": row["receiving_vessel_id"],
        "mode": row["mode"],
        "planned_kg": row["planned_kg"],
        "window_start": _dt(row, "window_start"),
        "window_end": _dt(row, "window_end"),
        "trailer_water_volume_l": row["trailer_water_volume_l"],
        "trailer_final_pressure_bar": row["trailer_final_pressure_bar"],
        "departed_at": _dt(row, "departed_at"),
        "arrived_at": row["arrived_at"],
        "accepted_at": row["accepted_at"],
        "transit_hours": row["transit_hours"],
        "boiloff_kg": row["boiloff_kg"],
        "heel_kg": row["heel_kg"],
        "net_receipt_kg": row["net_receipt_kg"],
        "status": row["status"],
        "reject_reason": row["reject_reason"],
        "reschedule_count": row["reschedule_count"],
    }
    return _common(row, out)


def dispense_session(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "vehicle_class": row["vehicle_class"],
        "target_pressure_class": row["target_pressure_class"],
        "fill_protocol": row["fill_protocol"],
        "planned_kg": row["planned_kg"],
        "ambient_temp_c": row["ambient_temp_c"],
        "required_precool_c": row["required_precool_c"],
        "precool_temp_achieved_c": row["precool_temp_achieved_c"],
        "metered_kg": row["metered_kg"],
        "avg_dispense_pressure_bar": row["avg_dispense_pressure_bar"],
        "final_pressure_bar": row["final_pressure_bar"],
        "density_correction_factor": row["density_correction_factor"],
        "corrected_kg": row["corrected_kg"],
        "metering_error_pct": row["metering_error_pct"],
        "metering_within_tolerance": row["metering_within_tolerance"],
        "direct_cascade_kg": row["direct_cascade_kg"],
        "compressor_makeup_kg": row["compressor_makeup_kg"],
        "cascade_plan": row["cascade_plan"],
        "fill_status": row["fill_status"],
        "billing_status": row["billing_status"],
        "abort_reason": row["abort_reason"],
        "void_reason": row["void_reason"],
        "started_at": row["started_at"],
    }
    return _common(row, out)


def safety_event(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "kind": row["kind"],
        "severity": row["severity"],
        "affected_nozzle_count": row["affected_nozzle_count"],
        "detected_by": row["detected_by"],
        "opened_by_user_id": row["opened_by_user_id"],
        "cleared_by_user_id": row["cleared_by_user_id"],
        "opened_at": row["opened_at"],
        "acknowledged_at": row["acknowledged_at"],
        "cleared_at": row["cleared_at"],
        "status": row["status"],
        "corrective_action": row["corrective_action"],
    }
    return _common(row, out)


def responder_cert(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "responder_ref": row["responder_ref"],
        "cert_type": row["cert_type"],
        "valid_from": row["valid_from"],
        "expires_on": row["expires_on"],
        "is_current": derive.cert_is_current(row),
    }
    return _common(row, out)


def incentive_claim(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "program": row["program"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "production_lot_ids": list(row["production_lot_ids"]),
        "dispensed_kg": row["dispensed_kg"],
        "energy_mj": row["energy_mj"],
        "pathway_ci_gco2e_per_mj": row["pathway_ci_gco2e_per_mj"],
        "gross_credits_mt": row["gross_credits_mt"],
        "admin_fee_rate": row["admin_fee_rate"],
        "admin_fee_mt": row["admin_fee_mt"],
        "net_credits_mt": row["net_credits_mt"],
        "revision_round": row["revision_round"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "revision_note": row["revision_note"],
        "status": row["status"],
    }
    return _common(row, out)


def uptime_report(row):
    out = {
        "id": row["id"],
        "station_id": row["station_id"],
        "funding_agreement_id": row["funding_agreement_id"],
        "amended_from_report_id": row["amended_from_report_id"],
        "period_start": _dt(row, "period_start"),
        "period_end": _dt(row, "period_end"),
        "nozzle_count_snapshot": row["nozzle_count_snapshot"],
        "downtime_nozzle_minutes": row["downtime_nozzle_minutes"],
        "full_outage_minutes": row["full_outage_minutes"],
        "uptime_pct_nozzle_weighted": row["uptime_pct_nozzle_weighted"],
        "uptime_pct_station_level": row["uptime_pct_station_level"],
        "uptime_pct": row["uptime_pct"],
        "shortfall_points": row["shortfall_points"],
        "penalty_cents": row["penalty_cents"],
        "status": row["status"],
        "amend_reason": row["amend_reason"],
    }
    return _common(row, out)


# --------------------------------------------------------------------------
# lookup helpers used by the route modules
# --------------------------------------------------------------------------
def ledger_page(station_id, reason=None):
    return [(entry, value) for entry, value in derive.replay_ledger(station_id)
            if reason is None or entry["reason"] == reason]
