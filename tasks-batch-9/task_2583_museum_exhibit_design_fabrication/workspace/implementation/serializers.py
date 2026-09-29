"""Entity -> JSON serialisation.  Derived fields are computed at read time so the
conserved identities of PRD §2.7 can never drift."""

from decimal import Decimal

import calc
import helpers
from envelope import iso


def num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def project_json(project):
    counters = helpers.project_counters(project)
    return {
        "id": project["id"],
        "name": project["name"],
        "museum_name": project["museum_name"],
        "storyline_title": project["storyline_title"],
        "objective_codes": list(project["objective_codes"]),
        "target_open_date": iso(project["target_open_date"]),
        "contract_value_cents": project["contract_value_cents"],
        "max_concurrent_closures": project["max_concurrent_closures"],
        "phase": project["phase"],
        "posture": calc.posture_from_counters(
            counters["conservation_block_count"], counters["open_revision_count"],
            counters["conditional_case_count"], counters["pending_material_count"]),
        "conservation_veto_count": counters["conservation_veto_count"],
        "conservation_block_count": counters["conservation_block_count"],
        "open_revision_count": counters["open_revision_count"],
        "conditional_case_count": counters["conditional_case_count"],
        "pending_material_count": counters["pending_material_count"],
        "blocking_punch_count": counters["blocking_punch_count"],
        "committed_fabrication_cents": project["committed_fabrication_cents"],
        "retainage_held_cents": project["retainage_held_cents"],
        "warranty_reserve_cents": project["warranty_reserve_cents"],
        "released_cents": project["released_cents"],
        "uncommitted_cents": helpers.uncommitted_cents(project),
        "parts_commitment_years": project["parts_commitment_years"],
        "docent_kit_url": project["docent_kit_url"],
        "maintenance_manual_url": project["maintenance_manual_url"],
        "warranty_registered_at": iso(project["warranty_registered_at"]),
        "created_by_user_id": project["created_by_user_id"],
        "created_at": iso(project["created_at"]),
        "updated_at": iso(project["updated_at"]),
        "version": project["version"],
    }


def package_json(package):
    return {
        "id": package["id"],
        "project_id": package["project_id"],
        "superseded_by_package_id": package["superseded_by_package_id"],
        "stage": package["stage"],
        "status": package["status"],
        "egress_clear_width_cm": num(package["egress_clear_width_cm"]),
        "wheelchair_turning_radius_cm": num(package["wheelchair_turning_radius_cm"]),
        "peak_visitors_per_hour": package["peak_visitors_per_hour"],
        "circulation_area_sqm": num(package["circulation_area_sqm"]),
        "flow_capacity_score": num(package["flow_capacity_score"]),
        "accessibility_pass": package["accessibility_pass"],
        "review_round_count": package["review_round_count"],
        "revision_count": package["revision_count"],
        "submitted_by_user_id": package["submitted_by_user_id"],
        "approved_at": iso(package["approved_at"]),
        "created_at": iso(package["created_at"]),
        "updated_at": iso(package["updated_at"]),
        "version": package["version"],
    }


def round_json(review_round):
    return {
        "id": review_round["id"],
        "package_id": review_round["package_id"],
        "round_number": review_round["round_number"],
        "panel_roles": list(review_round["panel_roles"]),
        "required_vote_count": review_round["required_vote_count"],
        "cast_vote_count": review_round["cast_vote_count"],
        "approve_count": review_round["approve_count"],
        "revise_count": review_round["revise_count"],
        "veto_count": review_round["veto_count"],
        "status": review_round["status"],
        "decision_deadline_at": iso(review_round["decision_deadline_at"]),
        "decided_at": iso(review_round["decided_at"]),
        "swept_by_deadline": review_round["swept_by_deadline"],
        "created_at": iso(review_round["created_at"]),
        "updated_at": iso(review_round["updated_at"]),
        "version": review_round["version"],
    }


def vote_json(vote):
    return {
        "id": vote["id"],
        "round_id": vote["round_id"],
        "voter_role": vote["voter_role"],
        "voter_user_id": vote["voter_user_id"],
        "decision": vote["decision"],
        "comment": vote["comment"],
        "created_at": iso(vote["created_at"]),
    }


def zone_json(zone):
    reserved = helpers.zone_reserved_slots(zone)
    return {
        "id": zone["id"],
        "project_id": zone["project_id"],
        "zone_code": zone["zone_code"],
        "is_public_operating": zone["is_public_operating"],
        "visitor_route_order": zone["visitor_route_order"],
        "max_noise_dba": num(zone["max_noise_dba"]),
        "case_slot_capacity": zone["case_slot_capacity"],
        "reserved_case_slots": reserved,
        "available_case_slots": zone["case_slot_capacity"] - reserved,
        "closure_allowed": zone["closure_allowed"],
        "dust_settling_buffer_minutes": zone["dust_settling_buffer_minutes"],
        "occupancy_state": zone["occupancy_state"],
        "created_at": iso(zone["created_at"]),
        "updated_at": iso(zone["updated_at"]),
        "version": zone["version"],
    }


def case_json(case):
    envelope = helpers.case_envelope_of(case)
    volume = calc.case_volume_m3(case)
    return {
        "id": case["id"],
        "project_id": case["project_id"],
        "zone_id": case["zone_id"],
        "case_code": case["case_code"],
        "objective_code": case["objective_code"],
        "security_tier": case["security_tier"],
        "target_rh_pct": num(case["target_rh_pct"]),
        "rh_tolerance_pct": num(case["rh_tolerance_pct"]),
        "target_lux": num(case["target_lux"]),
        "uv_microwatt_per_lumen": num(case["uv_microwatt_per_lumen"]),
        "interior_l_cm": num(case["interior_l_cm"]),
        "interior_w_cm": num(case["interior_w_cm"]),
        "interior_h_cm": num(case["interior_h_cm"]),
        "air_exchanges_per_day": num(case["air_exchanges_per_day"]),
        "case_volume_m3": num(volume),
        "silica_gel_kg": num(calc.silica_gel_kg(case, volume)),
        "placed_artifact_count": helpers.placed_artifact_count(case),
        "required_rh_min_pct": num(envelope["required_rh_min_pct"]),
        "required_rh_max_pct": num(envelope["required_rh_max_pct"]),
        "allowed_lux": num(envelope["allowed_lux"]),
        "env_feasible": envelope["env_feasible"],
        "security_ok": envelope["security_ok"],
        "status": case["status"],
        "mount_status": case["mount_status"],
        "conditions": case["conditions"],
        "decided_at": iso(case["decided_at"]),
        "created_at": iso(case["created_at"]),
        "updated_at": iso(case["updated_at"]),
        "version": case["version"],
    }


def artifact_json(artifact):
    return {
        "id": artifact["id"],
        "project_id": artifact["project_id"],
        "assigned_case_id": artifact["assigned_case_id"],
        "accession_number": artifact["accession_number"],
        "material_class": artifact["material_class"],
        "required_rh_min_pct": num(artifact["required_rh_min_pct"]),
        "required_rh_max_pct": num(artifact["required_rh_max_pct"]),
        "max_lux": num(artifact["max_lux"]),
        "security_class": artifact["security_class"],
        "condition_status": artifact["condition_status"],
        "placement_status": artifact["placement_status"],
        "created_at": iso(artifact["created_at"]),
        "updated_at": iso(artifact["updated_at"]),
        "version": artifact["version"],
    }


def interactive_json(interactive):
    return {
        "id": interactive["id"],
        "project_id": interactive["project_id"],
        "code": interactive["code"],
        "kind": interactive["kind"],
        "objective_code": interactive["objective_code"],
        "expected_daily_uses": interactive["expected_daily_uses"],
        "duty_hours_per_day": num(interactive["duty_hours_per_day"]),
        "mtbf_cycles": interactive["mtbf_cycles"],
        "parts_availability_years": interactive["parts_availability_years"],
        "warranty_months": interactive["warranty_months"],
        "measured_daily_uses": interactive["measured_daily_uses"],
        "measured_mtbf_cycles": interactive["measured_mtbf_cycles"],
        "durability_index_spec": num(interactive["durability_index_spec"]),
        "durability_index_verified": num(interactive["durability_index_verified"]),
        "maintenance_tier": calc.maintenance_tier(interactive),
        "prototype_iteration": interactive["prototype_iteration"],
        "status": interactive["status"],
        "submitted_by_user_id": interactive["submitted_by_user_id"],
        "created_at": iso(interactive["created_at"]),
        "updated_at": iso(interactive["updated_at"]),
        "version": interactive["version"],
    }


def material_json(material):
    return {
        "id": material["id"],
        "project_id": material["project_id"],
        "material_name": material["material_name"],
        "used_in": material["used_in"],
        "oddy_test_result": material["oddy_test_result"],
        "voc_mg_per_m2_day": num(material["voc_mg_per_m2_day"]),
        "formaldehyde_ppm": num(material["formaldehyde_ppm"]),
        "cure_days": material["cure_days"],
        "verdict": material["verdict"],
        "status": material["status"],
        "conditions": material["conditions"],
        "decided_at": iso(material["decided_at"]),
        "created_at": iso(material["created_at"]),
        "updated_at": iso(material["updated_at"]),
        "version": material["version"],
    }


def drawing_json(drawing):
    return {
        "id": drawing["id"],
        "project_id": drawing["project_id"],
        "material_spec_id": drawing["material_spec_id"],
        "subject_case_id": drawing["subject_case_id"],
        "subject_interactive_id": drawing["subject_interactive_id"],
        "drawing_number": drawing["drawing_number"],
        "revision": drawing["revision"],
        "complexity_tier": drawing["complexity_tier"],
        "shop_hours": num(drawing["shop_hours"]),
        "material_area_m2": num(drawing["material_area_m2"]),
        "finish_grade": drawing["finish_grade"],
        "estimate_labor_cents": drawing["estimate_labor_cents"],
        "estimate_material_cents": drawing["estimate_material_cents"],
        "estimate_finishing_cents": drawing["estimate_finishing_cents"],
        "estimate_total_cents": drawing["estimate_total_cents"],
        "actual_shop_hours": num(drawing["actual_shop_hours"]),
        "actual_waste_factor": num(drawing["actual_waste_factor"]),
        "actual_labor_cents": drawing["actual_labor_cents"],
        "actual_material_cents": drawing["actual_material_cents"],
        "actual_finishing_cents": drawing["actual_finishing_cents"],
        "actual_cost_cents": drawing["actual_cost_cents"],
        "status": drawing["status"],
        "submitted_by_user_id": drawing["submitted_by_user_id"],
        "void_reason": drawing["void_reason"],
        "created_at": iso(drawing["created_at"]),
        "updated_at": iso(drawing["updated_at"]),
        "version": drawing["version"],
    }


def window_json(window):
    return {
        "id": window["id"],
        "project_id": window["project_id"],
        "zone_id": window["zone_id"],
        "work_class": window["work_class"],
        "noise_dba": num(window["noise_dba"]),
        "starts_at": iso(window["starts_at"]),
        "ends_at": iso(window["ends_at"]),
        "requires_gallery_closure": window["requires_gallery_closure"],
        "pre_access_buffer_minutes": window["pre_access_buffer_minutes"],
        "settling_buffer_minutes": window["settling_buffer_minutes"],
        "effective_start_at": iso(window["effective_start_at"]),
        "effective_end_at": iso(window["effective_end_at"]),
        "status": window["status"],
        "denial_reason": window["denial_reason"],
        "requested_by_user_id": window["requested_by_user_id"],
        "created_at": iso(window["created_at"]),
        "updated_at": iso(window["updated_at"]),
        "version": window["version"],
    }


def punch_json(item):
    return {
        "id": item["id"],
        "project_id": item["project_id"],
        "interactive_id": item["interactive_id"],
        "case_id": item["case_id"],
        "severity": item["severity"],
        "description": item["description"],
        "status": item["status"],
        "raised_by_role": item["raised_by_role"],
        "raised_by_user_id": item["raised_by_user_id"],
        "verified_by_user_id": item["verified_by_user_id"],
        "verification_note": item["verification_note"],
        "waiver_reason": item["waiver_reason"],
        "verified_at": iso(item["verified_at"]),
        "created_at": iso(item["created_at"]),
        "updated_at": iso(item["updated_at"]),
        "version": item["version"],
    }
