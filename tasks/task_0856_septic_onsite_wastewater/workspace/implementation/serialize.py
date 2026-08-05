"""Entity -> JSON projections. Every datetime goes through util.render_dt."""
from decimal import Decimal

import calc
import store
from util import num, render_dt


def _f(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return num(value)
    return value


def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = render_dt(rec["created_at"])
    if "updated_at" in rec:
        out["updated_at"] = render_dt(rec["updated_at"])
    if "version" in rec:
        out["version"] = rec["version"]
    return out


def parcel(rec):
    return _common(rec, {
        "apn": rec["apn"],
        "county_code": rec["county_code"],
        "owner_user_id": rec["owner_user_id"],
        "site_address": rec["site_address"],
        "lot_size_sqft": rec["lot_size_sqft"],
        "water_source": rec["water_source"],
        "max_design_flow_gpd": rec["max_design_flow_gpd"],
        "permitted_design_flow_gpd": rec["permitted_design_flow_gpd"],
        "fees_assessed_cents": rec["fees_assessed_cents"],
        "fees_paid_cents": rec["fees_paid_cents"],
        "fees_credited_cents": rec["fees_credited_cents"],
        "fee_balance_cents": rec["fee_balance_cents"],
        "open_repair_order_count": rec["open_repair_order_count"],
        "water_quality_flag": rec["water_quality_flag"],
        "risk_tier": rec["risk_tier"],
        "transfer_hold": rec["transfer_hold"],
    })


def well(rec):
    return _common(rec, {
        "parcel_id": rec["parcel_id"],
        "well_type": rec["well_type"],
        "location_x_ft": _f(rec["location_x_ft"]),
        "location_y_ft": _f(rec["location_y_ft"]),
        "depth_ft": rec["depth_ft"],
        "advisory_status": rec["advisory_status"],
        "last_sample_collected_at": render_dt(rec["last_sample_collected_at"]),
    })


def water_sample(rec):
    return _common(rec, {
        "well_id": rec["well_id"],
        "collected_at": render_dt(rec["collected_at"]),
        "nitrate_mg_l": _f(rec["nitrate_mg_l"]),
        "coliform_present": rec["coliform_present"],
        "result": rec["result"],
        "exceedance_reasons": list(rec["exceedance_reasons"]),
    })


def perc_hole(hole):
    return {
        "hole_number": hole["hole_number"],
        "drop_inches": _f(hole["drop_inches"]),
        "elapsed_minutes": _f(hole["elapsed_minutes"]),
        "presoak_ok": hole["presoak_ok"],
        "valid": hole["valid"],
        "rate_min_per_in": _f(hole["rate_min_per_in"]),
    }


def site_evaluation(rec):
    return _common(rec, {
        "parcel_id": rec["parcel_id"],
        "evaluator_user_id": rec["evaluator_user_id"],
        "evaluated_on": render_dt(rec["evaluated_on"]),
        "soil_group": rec["soil_group"],
        "depth_to_limiting_layer_in": rec["depth_to_limiting_layer_in"],
        "perc_holes": [perc_hole(h) for h in rec["perc_holes"]],
        "preliminary_perc_rate_min_per_in": _f(rec["preliminary_perc_rate_min_per_in"]),
        "certified_perc_rate_min_per_in": _f(rec["certified_perc_rate_min_per_in"]),
        "soil_loading_rate_gpd_per_sqft": _f(rec["soil_loading_rate_gpd_per_sqft"]),
        "valid_until": render_dt(rec["valid_until"]),
        "status": rec["status"],
        "review_note": rec["review_note"],
        "revision_round": rec["revision_round"],
    })


def system_design(rec):
    return _common(rec, {
        "site_evaluation_id": rec["site_evaluation_id"],
        "designer_user_id": rec["designer_user_id"],
        "system_type": rec["system_type"],
        "bedrooms": rec["bedrooms"],
        "tank_capacity_gal": rec["tank_capacity_gal"],
        "drainfield_x_ft": _f(rec["drainfield_x_ft"]),
        "drainfield_y_ft": _f(rec["drainfield_y_ft"]),
        "design_flow_gpd": rec["design_flow_gpd"],
        "required_drainfield_sqft": rec["required_drainfield_sqft"],
        "nearest_well_distance_ft": _f(rec["nearest_well_distance_ft"]),
        "required_setback_ft": _f(rec["required_setback_ft"]),
        "setback_status": rec["setback_status"],
        "status": rec["status"],
        "review_ehs_user_id": rec["review_ehs_user_id"],
        "revision_round": rec["revision_round"],
    })


def contractor(rec, clock):
    return _common(rec, {
        "business_name": rec["business_name"],
        "license_number": rec["license_number"],
        "license_class": rec["license_class"],
        "license_expires_on": render_dt(rec["license_expires_on"]),
        "bond_amount_cents": rec["bond_amount_cents"],
        "status": rec["status"],
        "effective_status": calc.contractor_effective_status(
            rec["status"], rec["license_expires_on"], clock),
    })


def construction_permit(rec):
    return _common(rec, {
        "system_design_id": rec["system_design_id"],
        "parcel_id": rec["parcel_id"],
        "contractor_id": rec["contractor_id"],
        "permit_number": rec["permit_number"],
        "valid_from": render_dt(rec["valid_from"]),
        "valid_until": render_dt(rec["valid_until"]),
        "design_flow_gpd": rec["design_flow_gpd"],
        "fee_cents": rec["fee_cents"],
        "status": rec["status"],
        "cover_inspection_passed_at": render_dt(rec["cover_inspection_passed_at"]),
    })


def inspection(rec):
    return _common(rec, {
        "construction_permit_id": rec["construction_permit_id"],
        "contractor_id": rec["contractor_id"],
        "inspection_type": rec["inspection_type"],
        "inspector_user_id": rec["inspector_user_id"],
        "scheduled_start": render_dt(rec["scheduled_start"]),
        "scheduled_end": render_dt(rec["scheduled_end"]),
        "status": rec["status"],
        "result_recorded_at": render_dt(rec["result_recorded_at"]),
        "deficiency_codes": list(rec["deficiency_codes"]),
        "reinspection_round": rec["reinspection_round"],
    })


def operating_permit(rec):
    return _common(rec, {
        "parcel_id": rec["parcel_id"],
        "construction_permit_id": rec["construction_permit_id"],
        "household_size": rec["household_size"],
        "tank_capacity_gal": rec["tank_capacity_gal"],
        "issued_on": render_dt(rec["issued_on"]),
        "expires_on": render_dt(rec["expires_on"]),
        "last_pumped_on": render_dt(rec["last_pumped_on"]),
        "pumping_interval_months": rec["pumping_interval_months"],
        "next_pumping_due_on": render_dt(rec["next_pumping_due_on"]),
        "monitoring_required": rec["monitoring_required"],
        "status": rec["status"],
        "compliance_status": rec["compliance_status"],
    })


def pumping_record(rec):
    return _common(rec, {
        "operating_permit_id": rec["operating_permit_id"],
        "contractor_id": rec["contractor_id"],
        "pumped_on": render_dt(rec["pumped_on"]),
        "gallons_removed": rec["gallons_removed"],
        "sludge_depth_in": _f(rec["sludge_depth_in"]),
        "scum_depth_in": _f(rec["scum_depth_in"]),
        "accepted": rec["accepted"],
    })


def repair_order(rec):
    return _common(rec, {
        "parcel_id": rec["parcel_id"],
        "operating_permit_id": rec["operating_permit_id"],
        "failure_type": rec["failure_type"],
        "reported_on": render_dt(rec["reported_on"]),
        "severity": rec["severity"],
        "compliance_deadline": render_dt(rec["compliance_deadline"]),
        "issued_by_user_id": rec["issued_by_user_id"],
        "closed_by_user_id": rec["closed_by_user_id"],
        "extension_count": rec["extension_count"],
        "status": rec["status"],
    })


def transfer_inspection(rec):
    return _common(rec, {
        "parcel_id": rec["parcel_id"],
        "operating_permit_id": rec["operating_permit_id"],
        "requested_on": render_dt(rec["requested_on"]),
        "buyer_name": rec["buyer_name"],
        "seller_name": rec["seller_name"],
        "inspection_mode": rec["inspection_mode"],
        "expedited": rec["expedited"],
        "tank_condition": rec["tank_condition"],
        "drainfield_condition": rec["drainfield_condition"],
        "subtotal_cents": rec["subtotal_cents"],
        "expedite_fee_cents": rec["expedite_fee_cents"],
        "total_due_cents": rec["total_due_cents"],
        "certificate_grade": rec["certificate_grade"],
        "certified_at": render_dt(rec["certified_at"]),
        "certificate_valid_until": render_dt(rec["certificate_valid_until"]),
        "status": rec["status"],
    })


SERIALIZERS = {
    "parcel": parcel,
    "well": well,
    "water_sample": water_sample,
    "site_evaluation": site_evaluation,
    "system_design": system_design,
    "construction_permit": construction_permit,
    "inspection": inspection,
    "operating_permit": operating_permit,
    "pumping_record": pumping_record,
    "repair_order": repair_order,
    "transfer_inspection": transfer_inspection,
}


def many(kind, rows, clock=None):
    if kind == "contractor":
        return [contractor(r, clock) for r in rows]
    fn = SERIALIZERS[kind]
    return [fn(r) for r in rows]


def parcel_of_site_evaluation(evaluation):
    return store.parcels.get(evaluation["parcel_id"])
