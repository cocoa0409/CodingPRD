"""Resource representations."""
from decimal import Decimal


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def branch(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "region_code": r["region_code"],
        "yard_capacity_units": r["yard_capacity_units"],
        "daily_dispatch_capacity": r["daily_dispatch_capacity"],
        "labor_rate_cents_per_hour": r["labor_rate_cents_per_hour"],
        "status": r["status"],
        "units_in_yard": r["units_in_yard"],
        "units_available": r["units_available"],
        "utilization_pct": _num(r["utilization_pct"]),
    })
    return out


def jurisdiction(r):
    out = _common(r)
    out.update({
        "code": r["code"],
        "name": r["name"],
        "permit_required": r["permit_required"],
        "permit_lead_days": r["permit_lead_days"],
        "anchoring_standard": r["anchoring_standard"],
        "wind_zone": r["wind_zone"],
        "permit_fee_cents": r["permit_fee_cents"],
        "ada_ramp_required": r["ada_ramp_required"],
        "min_ramp_run_ratio": _num(r["min_ramp_run_ratio"]),
    })
    return out


def building_spec(r):
    out = _common(r)
    out.update({
        "model_code": r["model_code"],
        "width_ft": _num(r["width_ft"]),
        "length_ft": _num(r["length_ft"]),
        "sections": r["sections"],
        "floor_height_in": _num(r["floor_height_in"]),
        "base_monthly_rate_cents": r["base_monthly_rate_cents"],
        "delivery_base_cents": r["delivery_base_cents"],
        "install_base_cents": r["install_base_cents"],
        "replacement_value_cents": r["replacement_value_cents"],
        "max_occupancy": r["max_occupancy"],
        "floor_area_sqft": _num(r["floor_area_sqft"]),
    })
    return out


def config(r):
    out = _common(r)
    out.update({
        "building_spec_id": r["building_spec_id"],
        "name": r["name"],
        "private_offices": r["private_offices"],
        "restrooms": r["restrooms"],
        "partition_linear_ft": _num(r["partition_linear_ft"]),
        "hvac_tons": _num(r["hvac_tons"]),
        "config_surcharge_cents": r["config_surcharge_cents"],
        "status": r["status"],
    })
    return out


def unit(r):
    out = _common(r)
    out.update({
        "serial_number": r["serial_number"],
        "building_spec_id": r["building_spec_id"],
        "current_branch_id": r["current_branch_id"],
        "installed_config_id": r["installed_config_id"],
        "status": r["status"],
        "condition_grade": r["condition_grade"],
        "lifetime_relocations": r["lifetime_relocations"],
        "refurb_cycles": r["refurb_cycles"],
        "accumulated_damage_cents": r["accumulated_damage_cents"],
        "latest_quote_estimate_cents": r["latest_quote_estimate_cents"],
    })
    return out


def customer(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "billing_email": r["billing_email"],
        "credit_tier": r["credit_tier"],
        "credit_limit_cents": r["credit_limit_cents"],
        "outstanding_balance_cents": r["outstanding_balance_cents"],
        "credit_hold": r["credit_hold"],
    })
    return out


def lease(r):
    out = _common(r)
    out.update({
        "customer_id": r["customer_id"],
        "unit_id": r["unit_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "floorplan_configuration_id": r["floorplan_configuration_id"],
        "extends_lease_id": r["extends_lease_id"],
        "site_address": r["site_address"],
        "start_date": r["start_date"],
        "term_months": r["term_months"],
        "end_date": r["end_date"],
        "occupancy_status": r["occupancy_status"],
        "billing_status": r["billing_status"],
        "pinned_credit_tier": r["pinned_credit_tier"],
        "monthly_base_rate_cents": r["monthly_base_rate_cents"],
        "monthly_accessory_rate_cents": r["monthly_accessory_rate_cents"],
        "mobilization_fee_cents": r["mobilization_fee_cents"],
        "quoted_total_cents": r["quoted_total_cents"],
        "final_settlement_cents": r["final_settlement_cents"],
        "relocation_surcharge_cents": r["relocation_surcharge_cents"],
        "billed_to_date_cents": r["billed_to_date_cents"],
        "credited_cents": r["credited_cents"],
        "actual_vacated_date": r["actual_vacated_date"],
        "assessment_round": r["assessment_round"],
    })
    return out


def accessory_package(r):
    out = _common(r)
    out.update({
        "lease_id": r["lease_id"],
        "package_type": r["package_type"],
        "ramp_run_ft": _num(r["ramp_run_ft"]),
        "landing_count": r["landing_count"],
        "step_count": r["step_count"],
        "monthly_accessory_rate_cents": r["monthly_accessory_rate_cents"],
        "compliance_status": r["compliance_status"],
    })
    return out


def permit(r):
    out = _common(r)
    out.update({
        "lease_id": r["lease_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "foundation_type": r["foundation_type"],
        "status": r["status"],
        "permit_fee_cents": r["permit_fee_cents"],
        "submitted_on": r["submitted_on"],
        "decided_on": r["decided_on"],
        "reviewer_note": r["reviewer_note"],
    })
    return out


def job(r):
    out = _common(r)
    out.update({
        "lease_id": r["lease_id"],
        "unit_id": r["unit_id"],
        "origin_branch_id": r["origin_branch_id"],
        "destination_branch_id": r["destination_branch_id"],
        "job_type": r["job_type"],
        "scheduled_date": r["scheduled_date"],
        "mileage_miles": _num(r["mileage_miles"]),
        "crew_hours": _num(r["crew_hours"]),
        "new_site_address": r["new_site_address"],
        "status": r["status"],
        "transport_cost_cents": r["transport_cost_cents"],
        "cancellation_reason": r.get("cancellation_reason"),
    })
    return out


def assessment(r):
    out = _common(r)
    out.update({
        "unit_id": r["unit_id"],
        "lease_id": r["lease_id"],
        "logistics_job_id": r["logistics_job_id"],
        "assessor_user_id": r["assessor_user_id"],
        "status": r["status"],
        "dispute_rounds": r["dispute_rounds"],
        "condition_grade_before": r["condition_grade_before"],
        "condition_grade_after": r["condition_grade_after"],
        "gross_damage_cents": r["gross_damage_cents"],
        "wear_allowance_cents": r["wear_allowance_cents"],
        "chargeable_cents": r["chargeable_cents"],
        "dispute_reason": r["dispute_reason"],
    })
    return out


def line_item(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "damage_assessment_id": r["damage_assessment_id"],
        "component": r["component"],
        "severity": r["severity"],
        "quantity": _num(r["quantity"]),
        "wear_and_tear": r["wear_and_tear"],
        "repair_cost_cents": r["repair_cost_cents"],
    }


def refurb_order(r):
    out = _common(r)
    out.update({
        "unit_id": r["unit_id"],
        "branch_id": r["branch_id"],
        "damage_assessment_id": r["damage_assessment_id"],
        "scope": r["scope"],
        "labor_hours": _num(r["labor_hours"]),
        "parts_cost_cents": r["parts_cost_cents"],
        "target_condition_grade": r["target_condition_grade"],
        "estimated_cost_cents": r["estimated_cost_cents"],
        "actual_cost_cents": r["actual_cost_cents"],
        "status": r["status"],
        "approved_by_user_id": r["approved_by_user_id"],
        "rejection_reason": r["rejection_reason"],
    })
    return out
