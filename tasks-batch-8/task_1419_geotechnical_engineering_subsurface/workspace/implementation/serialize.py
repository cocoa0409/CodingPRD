"""Entity serializers: public wire shape = scaffold fields + common fields.

Computed rollups (posture, additional_committed_cents, claims_exposure_cents,
testing_invoice_cents, total_fee_cents, committed_rig_hours) are derived on
read so they are always consistent with child records (PRD 2.10).
"""

import calc
from db import fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def client(rec):
    out = {"name": rec["name"], "contact_email": rec["contact_email"]}
    out.update(_common(rec))
    return out


def project(rec):
    out = {
        "client_id": rec["client_id"],
        "name": rec["name"],
        "site_address": rec["site_address"],
        "target_report_date": rec["target_report_date"],
        "base_fee_cents": rec["base_fee_cents"],
        "additional_auth_cap_cents": rec["additional_auth_cap_cents"],
        "assumed_gwt_depth_ft": rec["assumed_gwt_depth_ft"],
        "status": rec["status"],
        "posture": calc.compute_posture(rec["id"]),
        "additional_committed_cents": calc.compute_additional_committed(rec["id"]),
        "claims_exposure_cents": calc.compute_claims_exposure(rec["id"]),
        "testing_invoice_cents": calc.compute_testing_invoice(rec["id"]),
        "total_fee_cents": calc.compute_total_fee(rec),
    }
    out.update(_common(rec))
    return out


def boring_plan(rec):
    out = {
        "project_id": rec["project_id"],
        "revision_no": rec["revision_no"],
        "status": rec["status"],
        "planned_boring_count": rec["planned_boring_count"],
        "planned_total_footage_ft": rec["planned_total_footage_ft"],
        "supersedes_plan_id": rec["supersedes_plan_id"],
        "mobilization_charged": rec["mobilization_charged"],
    }
    out.update(_common(rec))
    return out


def subcontractor(rec):
    out = {
        "name": rec["name"],
        "license_no": rec["license_no"],
        "day_rate_cents": rec["day_rate_cents"],
        "max_concurrent_rigs": rec["max_concurrent_rigs"],
        "standing": rec["standing"],
        "committed_rig_hours": calc.compute_committed_rig_hours(rec["id"]),
    }
    out.update(_common(rec))
    return out


def rig_assignment(rec):
    out = {
        "boring_id": rec["boring_id"],
        "subcontractor_id": rec["subcontractor_id"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def clearance(rec):
    out = {
        "boring_id": rec["boring_id"],
        "ticket_number": rec["ticket_number"],
        "issued_on": rec["issued_on"],
        "valid_days": rec["valid_days"],
        "expires_on": fmt_dt(rec["_expires_on"]),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def boring(rec):
    out = {
        "boring_plan_id": rec["boring_plan_id"],
        "offset_of_boring_id": rec["offset_of_boring_id"],
        "boring_no": rec["boring_no"],
        "planned_depth_ft": rec["planned_depth_ft"],
        "access_difficult": rec["access_difficult"],
        "status": rec["status"],
        "actual_depth_ft": rec["actual_depth_ft"],
        "rock_depth_ft": rec["rock_depth_ft"],
        "groundwater_depth_ft": rec["groundwater_depth_ft"],
        "avg_n60": rec["avg_n60"],
        "refusal_depth_ft": rec["refusal_depth_ft"],
        "drilling_cost_cents": rec["drilling_cost_cents"],
    }
    out.update(_common(rec))
    return out


def sample(rec):
    out = {
        "boring_id": rec["boring_id"],
        "depth_top_ft": rec["depth_top_ft"],
        "depth_bottom_ft": rec["depth_bottom_ft"],
        "sampler_type": rec["sampler_type"],
        "recovery_pct": rec["recovery_pct"],
        "custody_status": rec["custody_status"],
        "uscs_class": rec["uscs_class"],
    }
    out.update(_common(rec))
    return out


def lab_test_order(rec):
    out = {
        "project_id": rec["project_id"],
        "sample_id": rec["sample_id"],
        "test_type": rec["test_type"],
        "priority": rec["priority"],
        "fee_cents": rec["fee_cents"],
        "status": rec["status"],
        "rerun_count": rec["rerun_count"],
    }
    out.update(_common(rec))
    return out


def lab_test_result(rec):
    out = {
        "lab_test_order_id": rec["lab_test_order_id"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "percent_passing_200": rec["percent_passing_200"],
        "liquid_limit": rec["liquid_limit"],
        "plasticity_index": rec["plasticity_index"],
        "qu_psf": rec["qu_psf"],
        "moisture_content_pct": rec["moisture_content_pct"],
    }
    out.update(_common(rec))
    return out


def foundation_analysis(rec):
    out = {
        "project_id": rec["project_id"],
        "method": rec["method"],
        "fs_required": rec["fs_required"],
        "footing_width_ft": rec["footing_width_ft"],
        "applied_bearing_psf": rec["applied_bearing_psf"],
        "bearing_capacity_provisional_psf": rec["bearing_capacity_provisional_psf"],
        "bearing_capacity_final_psf": rec["bearing_capacity_final_psf"],
        "settlement_est_in": rec["settlement_est_in"],
        "deep_foundation_required": rec["deep_foundation_required"],
        "data_status": rec["data_status"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def report(rec):
    out = {
        "project_id": rec["project_id"],
        "revision_no": rec["revision_no"],
        "prepared_by_user_id": rec["prepared_by_user_id"],
        "sealed_by_pe_user_id": rec["sealed_by_pe_user_id"],
        "sealed_at": rec["sealed_at"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def observation_visit(rec):
    out = {
        "project_id": rec["project_id"],
        "visit_date": rec["visit_date"],
        "findings": rec["findings"],
        "observed_bearing_psf": rec["observed_bearing_psf"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def claim(rec):
    out = {
        "project_id": rec["project_id"],
        "observation_visit_id": rec["observation_visit_id"],
        "claimed_amount_cents": rec["claimed_amount_cents"],
        "basis_text": rec["basis_text"],
        "baseline_bearing_psf": rec["baseline_bearing_psf"],
        "quantum_report_baseline_cents": rec["quantum_report_baseline_cents"],
        "quantum_site_observed_cents": rec["quantum_site_observed_cents"],
        "awarded_amount_cents": rec["awarded_amount_cents"],
        "appeal_count": rec["appeal_count"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def exploration_authorization(rec):
    out = {
        "project_id": rec["project_id"],
        "authorized_amount_cents": rec["authorized_amount_cents"],
        "extra_boring_count": rec["extra_boring_count"],
        "consumed_boring_count": rec["consumed_boring_count"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out
