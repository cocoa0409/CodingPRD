"""Resource serializers -- explicit field sets straight from SCAFFOLD `entities`."""

from store import db


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def jurisdiction_out(row):
    authorized = 0
    for builder in db.builders.values():
        if builder["territory_code"] == row["territory_code"] and builder["status"] == "AUTHORIZED":
            authorized += 1
    out = {
        "code": row["code"],
        "name": row["name"],
        "state_code": row["state_code"],
        "territory_code": row["territory_code"],
        "freight_zone": row["freight_zone"],
        "max_authorized_builders": row["max_authorized_builders"],
        "exposure_category": row["exposure_category"],
        "design_wind_speed_mph": row["design_wind_speed_mph"],
        "ground_snow_load_psf": row["ground_snow_load_psf"],
        "seismic_design_category": row["seismic_design_category"],
        "criteria_revision": row["criteria_revision"],
        "authorized_builder_count": authorized,
    }
    out.update(_common(row))
    return out


def builder_out(row):
    out = {
        "jurisdiction_id": row["jurisdiction_id"],
        "name": row["name"],
        "territory_code": row["territory_code"],
        "tier": row["tier"],
        "credit_limit_cents": row["credit_limit_cents"],
        "credit_used_cents": row["credit_used_cents"],
        "credit_available_cents": row["credit_limit_cents"] - row["credit_used_cents"],
        "status": row["status"],
        "authorized_at": row["authorized_at"],
    }
    out.update(_common(row))
    return out


def configuration_out(row):
    out = {
        "builder_id": row["builder_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "clear_span_ft": row["clear_span_ft"],
        "bay_spacing_ft": row["bay_spacing_ft"],
        "bay_count": row["bay_count"],
        "eave_height_ft": row["eave_height_ft"],
        "roof_pitch_rise_per_12": row["roof_pitch_rise_per_12"],
        "panel_profile": row["panel_profile"],
        "panel_color": row["panel_color"],
        "insulation_r_value": row["insulation_r_value"],
        "building_length_ft": row["building_length_ft"],
        "footprint_sqft": row["footprint_sqft"],
        "roof_slope_factor": row["roof_slope_factor"],
        "panel_area_sqft": row["panel_area_sqft"],
        "design_wind_pressure_psf": row["design_wind_pressure_psf"],
        "dead_load_psf": row["dead_load_psf"],
        "roof_snow_load_psf": row["roof_snow_load_psf"],
        "estimated_frame_weight_lbs": row["estimated_frame_weight_lbs"],
        "criteria_revision_at_lock": row["criteria_revision_at_lock"],
        "status": row["status"],
        "locked_at": row["locked_at"],
    }
    out.update(_common(row))
    return out


def accessory_kit_out(row):
    out = {
        "configuration_id": row["configuration_id"],
        "kit_type": row["kit_type"],
        "quantity": row["quantity"],
        "unit_price_cents": row["unit_price_cents"],
        "unit_weight_lbs": row["unit_weight_lbs"],
        "erection_stage": row["erection_stage"],
        "extended_price_cents": row["extended_price_cents"],
        "extended_weight_lbs": row["extended_weight_lbs"],
    }
    out.update(_common(row))
    return out


def quote_out(row):
    out = {
        "builder_id": row["builder_id"],
        "configuration_id": row["configuration_id"],
        "freight_distance_miles": row["freight_distance_miles"],
        "adjustment_cents": row["adjustment_cents"],
        "quote_variant": row["quote_variant"],
        "billable_frame_weight_lbs": row["billable_frame_weight_lbs"],
        "steel_cost_cents": row["steel_cost_cents"],
        "panel_cost_cents": row["panel_cost_cents"],
        "accessory_cost_cents": row["accessory_cost_cents"],
        "subtotal_cents": row["subtotal_cents"],
        "billable_weight_lbs": row["billable_weight_lbs"],
        "billable_tons": row["billable_tons"],
        "freight_cost_cents": row["freight_cost_cents"],
        "pre_discount_total_cents": row["pre_discount_total_cents"],
        "tier_discount_rate": row["tier_discount_rate"],
        "volume_discount_rate": row["volume_discount_rate"],
        "total_discount_rate": row["total_discount_rate"],
        "quoted_price_cents": row["quoted_price_cents"],
        "valid_until": row["valid_until"],
        "issued_at": row["issued_at"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def design_out(row):
    out = {
        "configuration_id": row["configuration_id"],
        "design_variant": row["design_variant"],
        "governing_combination": row["governing_combination"],
        "governing_load_psf": row["governing_load_psf"],
        "tributary_load_kip_per_ft": row["tributary_load_kip_per_ft"],
        "required_moment_kip_ft": row["required_moment_kip_ft"],
        "frame_weight_lbs": row["frame_weight_lbs"],
        "shippable_weight_lbs": row["shippable_weight_lbs"],
        "component_count": row["component_count"],
        "revision_count": row["revision_count"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def component_out(row):
    # PRD 2.4: a component row carries only id and created_at -- no updated_at,
    # no version, because components are immutable.
    out = {
        "design_id": row["design_id"],
        "component_class": row["component_class"],
        "mark": row["mark"],
        "member_type": row["member_type"],
        "erection_stage": row["erection_stage"],
        "quantity": row["quantity"],
        "length_ft": row["length_ft"],
        "weight_per_ft": row["weight_per_ft"],
        "connection_type": row["connection_type"],
        "capacity_moment_kip_ft": row["capacity_moment_kip_ft"],
        "unit_weight_lbs": row["unit_weight_lbs"],
        "line_weight_lbs": row["line_weight_lbs"],
    }
    out.update(_common(row, versioned=False))
    return out


def drawing_package_out(row):
    out = {
        "design_id": row["design_id"],
        "jurisdiction_id": row["jurisdiction_id"],
        "sealing_license_state": row["sealing_license_state"],
        "sheet_count": row["sheet_count"],
        "criteria_revision_at_seal": row["criteria_revision_at_seal"],
        "sealed_at": row["sealed_at"],
        "sealed_by_user_id": row["sealed_by_user_id"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def order_out(row):
    out = {
        "quote_id": row["quote_id"],
        "builder_id": row["builder_id"],
        "configuration_id": row["configuration_id"],
        "engineering_design_id": row["engineering_design_id"],
        "drawing_package_id": row["drawing_package_id"],
        "job_site_code": row["job_site_code"],
        "requested_erection_start_date": row["requested_erection_start_date"],
        "site_delivery_capacity": row["site_delivery_capacity"],
        "engineering_status": row["engineering_status"],
        "production_status": row["production_status"],
        "permit_hold": row["permit_hold"],
        "commercial_hold": row["commercial_hold"],
        "final_price_cents": row["final_price_cents"],
        "price_delta_cents": row["price_delta_cents"],
        "total_shippable_weight_lbs": row["total_shippable_weight_lbs"],
        "assigned_weight_lbs": row["assigned_weight_lbs"],
        "unassigned_weight_lbs": row["unassigned_weight_lbs"],
        "released_at": row["released_at"],
    }
    out.update(_common(row))
    return out


def production_line_out(row):
    out = {
        "code": row["code"],
        "name": row["name"],
        "line_type": row["line_type"],
        "changeover_buffer_minutes": row["changeover_buffer_minutes"],
    }
    out.update(_common(row))
    return out


def production_lot_out(row):
    out = {
        "order_id": row["order_id"],
        "line_id": row["line_id"],
        "lot_type": row["lot_type"],
        "paint_color": row["paint_color"],
        "window_start": row["window_start"],
        "window_end": row["window_end"],
        "status": row["status"],
        "completed_at": row["completed_at"],
    }
    out.update(_common(row))
    return out


def shipment_load_out(row):
    out = {
        "order_id": row["order_id"],
        "carrier_name": row["carrier_name"],
        "erection_stage": row["erection_stage"],
        "component_marks": list(row["component_marks"]),
        "stage_sequence": row["stage_sequence"],
        "gross_weight_lbs": row["gross_weight_lbs"],
        "unload_window_start": row["unload_window_start"],
        "unload_window_end": row["unload_window_end"],
        "status": row["status"],
        "dispatched_at": row["dispatched_at"],
    }
    out.update(_common(row))
    return out
