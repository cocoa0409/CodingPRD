"""Entity serializers — exact field sets per SCAFFOLD 1.1 / PRD 2.5.
Internal keys (prefixed with "_") are never emitted. Computed fields that
are defined as live reads (initiative progress) are computed here.
"""

from __future__ import annotations

from services.core import initiative_progress


def program_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "sampling_protocol": p["sampling_protocol"],
        "admin_mode": p["admin_mode"],
        "active_vendor_id": p["active_vendor_id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def vendor_view(v: dict) -> dict:
    return {
        "id": v["id"],
        "program_id": v["program_id"],
        "name": v["name"],
        "cycle_budget_cents": v["cycle_budget_cents"],
        "cycle_budget_remaining_cents": v["cycle_budget_remaining_cents"],
        "status": v["status"],
        "superseded_at": v["superseded_at"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def cycle_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "label": c["label"],
        "cycle_index": c["cycle_index"],
        "discharge_window_start": c["discharge_window_start"],
        "discharge_window_end": c["discharge_window_end"],
        "fielding_start_date": c["fielding_start_date"],
        "fielding_end_date": c["fielding_end_date"],
        "target_sample_size": c["target_sample_size"],
        "status": c["status"],
        "sampled_count": c["sampled_count"],
        "completed_responses": c["completed_responses"],
        "eligible_denominator": c["eligible_denominator"],
        "response_rate": c["response_rate"],
        "publication_eligible": c["publication_eligible"],
        "scored_raw_composite_pcts": c["scored_raw_composite_pcts"],
        "scored_adjusted_composite_pcts": c["scored_adjusted_composite_pcts"],
        "scored_unit_breakdown": c["scored_unit_breakdown"],
        "scored_provider_breakdown": c["scored_provider_breakdown"],
        "scored_response_rate": c["scored_response_rate"],
        "scored_completed_responses": c["scored_completed_responses"],
        "published_star_rating": c["published_star_rating"],
        "published_at": c["published_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def unit_view(u: dict) -> dict:
    return {
        "id": u["id"],
        "program_id": u["program_id"],
        "name": u["name"],
        "unit_code": u["unit_code"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def provider_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "program_id": p["program_id"],
        "full_name": p["full_name"],
        "npi": p["npi"],
        "specialty": p["specialty"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def discharge_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "program_id": d["program_id"],
        "mrn": d["mrn"],
        "unit_id": d["unit_id"],
        "provider_id": d["provider_id"],
        "admit_date": d["admit_date"],
        "discharge_date": d["discharge_date"],
        "discharge_disposition": d["discharge_disposition"],
        "primary_dx_group": d["primary_dx_group"],
        "payer": d["payer"],
        "age_years": d["age_years"],
        "address_country": d["address_country"],
        "no_publicity_flag": d["no_publicity_flag"],
        "custody_status": d["custody_status"],
        "status": d["status"],
        "exclusion_reasons": d["exclusion_reasons"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def sample_case_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "cycle_id": c["cycle_id"],
        "discharge_id": c["discharge_id"],
        "vendor_id": c["vendor_id"],
        "unit_id": c["unit_id"],
        "provider_id": c["provider_id"],
        "mode_assigned": c["mode_assigned"],
        "postage_cost_cents": c["postage_cost_cents"],
        "billing_status": c["billing_status"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def response_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "cycle_id": r["cycle_id"],
        "mode_used": r["mode_used"],
        "nurse_comm_score": r["nurse_comm_score"],
        "doctor_comm_score": r["doctor_comm_score"],
        "cleanliness_score": r["cleanliness_score"],
        "overall_rating_score": r["overall_rating_score"],
        "comment_text": r["comment_text"],
        "received_at": r["received_at"],
        "is_late": r["is_late"],
        "status": r["status"],
        "has_escalated_recovery": r["has_escalated_recovery"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def initiative_view(i: dict) -> dict:
    pinned, rolling = initiative_progress(i)
    return {
        "id": i["id"],
        "unit_id": i["unit_id"],
        "program_id": i["program_id"],
        "domain": i["domain"],
        "baseline_cycle_id": i["baseline_cycle_id"],
        "evaluation_cycle_id": i["evaluation_cycle_id"],
        "target_score": i["target_score"],
        "baseline_score": i["baseline_score"],
        "status": i["status"],
        "progress_pinned": pinned,
        "progress_rolling": rolling,
        "achieved_at": i["achieved_at"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ticket_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "unit_id": t["unit_id"],
        "program_id": t["program_id"],
        "response_id": t["response_id"],
        "domain": t["domain"],
        "priority": t["priority"],
        "status": t["status"],
        "acknowledged_at": t["acknowledged_at"],
        "acknowledged_within_sla": t["acknowledged_within_sla"],
        "resolution_note": t["resolution_note"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }
