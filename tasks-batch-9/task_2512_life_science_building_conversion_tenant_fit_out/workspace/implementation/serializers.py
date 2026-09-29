"""Wire representations. Field sets are exactly the scaffold entity definitions
plus the four shared server-managed properties (PRD 2.4).

Computed fields (capacity pools, discipline lists, delivery_risk,
passed_script_count, negotiation_round_count, floor control-area entitlement) are
derived on read so the two conservation identities of PRD 2.10 cannot drift.
"""
import calc
import queries
from util import fmt_iso, num


def _common(record):
    return {
        "id": record["id"],
        "created_at": fmt_iso(record["created_at"]),
        "updated_at": fmt_iso(record["updated_at"]),
        "version": record["version"],
    }


def building(record):
    out = _common(record)
    out.update({
        "name": record["name"],
        "address_city": record["address_city"],
        "occupancy_status": record["occupancy_status"],
        "published_floor_to_floor_ft": num(record["published_floor_to_floor_ft"]),
        "published_live_load_psf": num(record["published_live_load_psf"]),
        "published_vibration_class": record["published_vibration_class"],
        "exhaust_riser_capacity_cfm": num(record["exhaust_riser_capacity_cfm"]),
        "emergency_power_capacity_kw": num(record["emergency_power_capacity_kw"]),
        "chilled_water_capacity_tons": num(record["chilled_water_capacity_tons"]),
        "suitability_state": record["suitability_state"],
        "latest_assessment_verdict": record["latest_assessment_verdict"],
    })
    pools = calc.building_pools(record)
    for key, value in pools.items():
        out[key] = num(value)
    covered, complete = calc.scope_discipline_lists(record)
    out["scope_disciplines_covered"] = covered
    out["scope_disciplines_complete"] = complete
    return out


def floor(record):
    out = _common(record)
    out.update({
        "building_id": record["building_id"],
        "floor_number": record["floor_number"],
        "floor_to_floor_ft": num(record["floor_to_floor_ft"]),
        "live_load_psf": num(record["live_load_psf"]),
        "vibration_class": record["vibration_class"],
        "sprinklered": record["sprinklered"],
        "control_areas_allowed": calc.control_areas_allowed(record),
        "percent_maq": num(calc.percent_maq(record)),
    })
    return out


def assessment(record):
    out = _common(record)
    out.update({
        "building_id": record["building_id"],
        "assessment_basis": record["assessment_basis"],
        "measured_floor_to_floor_ft": num(record["measured_floor_to_floor_ft"]),
        "measured_live_load_psf": num(record["measured_live_load_psf"]),
        "measured_vibration_class": record["measured_vibration_class"],
        "required_vibration_class": record["required_vibration_class"],
        "required_exhaust_cfm": num(record["required_exhaust_cfm"]),
        "required_power_kw": num(record["required_power_kw"]),
        "height_credit": record["height_credit"],
        "structural_credit": record["structural_credit"],
        "vibration_credit": record["vibration_credit"],
        "utility_credit": record["utility_credit"],
        "utility_headroom_ratio": num(record["utility_headroom_ratio"]),
        "suitability_score": num(record["suitability_score"]),
        "hard_fail_capped": record["hard_fail_capped"],
        "verdict": record["verdict"],
        "status": record["status"],
        "decided_by_user_id": record["decided_by_user_id"],
        "return_note": record["return_note"],
    })
    return out


def scope_item(record):
    out = _common(record)
    out.update({
        "building_id": record["building_id"],
        "discipline": record["discipline"],
        "description": record["description"],
        "capacity_delta_cfm": num(record["capacity_delta_cfm"]),
        "capacity_delta_kw": num(record["capacity_delta_kw"]),
        "budget_usd": num(record["budget_usd"]),
        "status": record["status"],
        "completed_at": fmt_iso(record["completed_at"]),
    })
    return out


def tenant(record):
    out = _common(record)
    out.update({
        "legal_name": record["legal_name"],
        "research_type": record["research_type"],
        "credit_tier": record["credit_tier"],
        "lab_premium_psf": num(record["lab_premium_psf"]),
        "required_commissioning_scripts": list(record["required_commissioning_scripts"]),
    })
    return out


def lease(record):
    out = _common(record)
    out.update({
        "tenant_id": record["tenant_id"],
        "building_id": record["building_id"],
        "premises_floor_id": record["premises_floor_id"],
        "rentable_sf": record["rentable_sf"],
        "term_months": record["term_months"],
        "base_rent_psf": num(record["base_rent_psf"]),
        "delivery_deadline": fmt_iso(record["delivery_deadline"]),
        "status": record["status"],
        "negotiation_round_count": len(queries.proposals_of(record["id"])),
        "accepted_proposal_round": record["accepted_proposal_round"],
        "accepted_allowance_psf": num(record["accepted_allowance_psf"]),
        "lab_premium_psf_applied": num(record["lab_premium_psf_applied"]),
        "provisional_authorized_ti_usd": num(record["provisional_authorized_ti_usd"]),
        "volume_credit_psf": num(record["volume_credit_psf"]),
        "final_allowance_psf": num(record["final_allowance_psf"]),
        "ti_authorized_usd": num(record["ti_authorized_usd"]),
        "ti_uncommitted_usd": num(record["ti_uncommitted_usd"]),
        "ti_committed_usd": num(record["ti_committed_usd"]),
        "ti_disbursed_usd": num(record["ti_disbursed_usd"]),
        "ti_forfeited_usd": num(record["ti_forfeited_usd"]),
        "last_disbursement_usd": num(record["last_disbursement_usd"]),
        "restoration_escrow_required_usd": num(record["restoration_escrow_required_usd"]),
        "restoration_escrow_held_usd": num(record["restoration_escrow_held_usd"]),
        "restoration_liability_usd": num(record["restoration_liability_usd"]),
        "restoration_cash_due_usd": num(record["restoration_cash_due_usd"]),
        "restoration_escrow_refunded_usd": num(record["restoration_escrow_refunded_usd"]),
        "terms_accepted_by_user_id": record["terms_accepted_by_user_id"],
        "executed_by_user_id": record["executed_by_user_id"],
        "executed_at": fmt_iso(record["executed_at"]),
        "expiration_date": fmt_iso(record["expiration_date"]),
    })
    return out


def proposal(record):
    out = _common(record)
    out.update({
        "lease_id": record["lease_id"],
        "round_number": record["round_number"],
        "proposed_by": record["proposed_by"],
        "authored_by_user_id": record["authored_by_user_id"],
        "proposed_allowance_psf": num(record["proposed_allowance_psf"]),
        "note": record["note"],
        "expires_at": fmt_iso(record["expires_at"]),
        "status": record["status"],
        "accepted_by_user_id": record["accepted_by_user_id"],
    })
    return out


def project(record):
    out = _common(record)
    out.update({
        "lease_id": record["lease_id"],
        "floor_id": record["floor_id"],
        "design_exhaust_cfm": num(record["design_exhaust_cfm"]),
        "design_power_kw": num(record["design_power_kw"]),
        "scope_summary": record["scope_summary"],
        "permit_status": record["permit_status"],
        "construction_status": record["construction_status"],
        "delivery_risk": calc.delivery_risk(record),
        "required_commissioning_scripts": list(record["required_commissioning_scripts"]),
        "passed_script_count": calc.passed_script_count(record),
        "permit_applied_at": fmt_iso(record["permit_applied_at"]),
        "permit_issued_at": fmt_iso(record["permit_issued_at"]),
        "accepted_at": fmt_iso(record["accepted_at"]),
    })
    return out


def phase(record):
    out = _common(record)
    out.update({
        "project_id": record["project_id"],
        "predecessor_phase_id": record["predecessor_phase_id"],
        "affected_amenity_id": record["affected_amenity_id"],
        "sequence_no": record["sequence_no"],
        "premium_class": record["premium_class"],
        "work_class": record["work_class"],
        "window_start": fmt_iso(record["window_start"]),
        "window_end": fmt_iso(record["window_end"]),
        "hard_cost_usd": num(record["hard_cost_usd"]),
        "restoration_cost_usd": num(record["restoration_cost_usd"]),
        "status": record["status"],
        "prior_status": record["prior_status"],
        "hold_reason": record["hold_reason"],
        "ti_eligible_usd": num(record["ti_eligible_usd"]),
        "ti_committed_usd": num(record["ti_committed_usd"]),
        "ti_disbursed_usd": num(record["ti_disbursed_usd"]),
    })
    return out


def reservation(record):
    out = _common(record)
    out.update({
        "project_id": record["project_id"],
        "building_id": record["building_id"],
        "exhaust_cfm": num(record["exhaust_cfm"]),
        "power_kw": num(record["power_kw"]),
        "status": record["status"],
    })
    return out


def permit(record):
    out = _common(record)
    out.update({
        "project_id": record["project_id"],
        "floor_id": record["floor_id"],
        "hazard_class": record["hazard_class"],
        "use_condition": record["use_condition"],
        "quantity_gal": num(record["quantity_gal"]),
        "control_area_index": record["control_area_index"],
        "allowance_per_control_area_gal": num(record["allowance_per_control_area_gal"]),
        "aggregate_allowance_gal": num(
            calc.aggregate_allowance_gal(
                queries.floor_of_permit(record), record["allowance_per_control_area_gal"]
            )
        ),
        "status": record["status"],
        "decision_reason": record["decision_reason"],
    })
    return out


def amenity(record):
    out = _common(record)
    out.update({
        "building_id": record["building_id"],
        "name": record["name"],
        "amenity_type": record["amenity_type"],
        "serving_floor_number": record["serving_floor_number"],
        "concurrent_capacity": record["concurrent_capacity"],
        "vibration_sensitive": record["vibration_sensitive"],
        "utility_draw_kw": num(record["utility_draw_kw"]),
    })
    return out


def allocation(record):
    out = _common(record)
    out.update({
        "amenity_id": record["amenity_id"],
        "project_id": record["project_id"],
        "window_start": fmt_iso(record["window_start"]),
        "window_end": fmt_iso(record["window_end"]),
        "headcount": record["headcount"],
        "status": record["status"],
    })
    return out


def commissioning_record(record):
    out = _common(record)
    out.update({
        "project_id": record["project_id"],
        "script_type": record["script_type"],
        "scheduled_for": fmt_iso(record["scheduled_for"]),
        "executed_by_user_id": record["executed_by_user_id"],
        "witnessed_by_user_id": record["witnessed_by_user_id"],
        "measured_value": num(record["measured_value"]),
        "result": record["result"],
        "status": record["status"],
    })
    return out
