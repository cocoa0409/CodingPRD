"""Entity serializers — exact public field sets per SCAFFOLD §1.1.

Common fields (PRD §2.4): id, created_at, updated_at, version on every
primary resource. DailySiteLog is the sole exception: only id + created_at.
Computed fields (strike_count, contract_price_cents, price_variant,
remaining_cents, variance_cents) are derived at read time.
"""
from services import (
    strike_count, project_price, line_remaining, line_variance,
)


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_contractor(e):
    d = _common(e)
    d.update({"name": e["name"], "license_no": e["license_no"]})
    return d


def ser_homeowner(e):
    d = _common(e)
    d.update({"name": e["name"], "email": e["email"], "phone": e["phone"]})
    return d


def ser_subcontractor(e):
    d = _common(e)
    d.update({"name": e["name"], "trade": e["trade"]})
    return d


def ser_project(e):
    d = _common(e)
    price, variant = project_price(e)
    d.update({
        "homeowner_id": e["homeowner_id"],
        "contractor_id": e["contractor_id"],
        "address": e["address"],
        "basement_sqft": e["basement_sqft"],
        "base_contract_cents": e["base_contract_cents"],
        "status": e["status"],
        "strike_count": strike_count(e),
        "last_resumed_at": e["last_resumed_at"],
        "contract_price_cents": price,
        "price_variant": variant,
        "approved_design_id": e["approved_design_id"],
    })
    return d


def ser_assessment(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "assessment_kind": e["assessment_kind"],
        "slab_moisture_lbs": e["slab_moisture_lbs"],
        "interior_rh_pct": e["interior_rh_pct"],
        "efflorescence_observed": e["efflorescence_observed"],
        "grading_deficit": e["grading_deficit"],
        "egress_windows_existing": e["egress_windows_existing"],
        "ceiling_height_in": e["ceiling_height_in"],
        "remediation_notes": e["remediation_notes"],
        "moisture_risk_score": e["moisture_risk_score"],
        "risk_band": e["risk_band"],
        "status": e["status"],
    })
    return d


def ser_design(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "layout_notes": e["layout_notes"],
        "mechanical_relocations": e["mechanical_relocations"],
        "revision_number": e["revision_number"],
        "revision_notes": e["revision_notes"],
        "status": e["status"],
    })
    return d


def ser_permit(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "bedroom_count": e["bedroom_count"],
        "windows": e["windows"],
        "ceiling_height_in": e["ceiling_height_in"],
        "finished_area_sqft": e["finished_area_sqft"],
        "low_area_sqft": e["low_area_sqft"],
        "prohibited_area_sqft": e["prohibited_area_sqft"],
        "pinned_design_id": e["pinned_design_id"],
        "pinned_design_revision": e["pinned_design_revision"],
        "egress_compliant": e["egress_compliant"],
        "ceiling_compliant": e["ceiling_compliant"],
        "amendment_count": e["amendment_count"],
        "issued_at": e["issued_at"],
        "status": e["status"],
    })
    return d


def ser_allowance_line(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "name": e["name"],
        "budgeted_cents": e["budgeted_cents"],
        "reserved_cents": e["reserved_cents"],
        "drawn_cents": e["drawn_cents"],
        "selected": e["selected"],
        "actual_cents": e["actual_cents"],
        "remaining_cents": line_remaining(e),
        "variance_cents": line_variance(e),
    })
    return d


def ser_change_order(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "scope_description": e["scope_description"],
        "kind": e["kind"],
        "scope_items": e["scope_items"],
        "allowance_draws": e["allowance_draws"],
        "price_delta_cents": e["price_delta_cents"],
        "status": e["status"],
    })
    return d


def ser_work_phase(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "subcontractor_id": e["subcontractor_id"],
        "trade": e["trade"],
        "zone": e["zone"],
        "start_date": e["start_date"],
        "end_date": e["end_date"],
        "crew_count": e["crew_count"],
        "predecessor_ids": e["predecessor_ids"],
        "requires_rough_in": e["requires_rough_in"],
        "pre_block_status": e["pre_block_status"],
        "status": e["status"],
    })
    return d


def ser_site_log(e):
    # DailySiteLog carries only id + created_at (PRD §2.4).
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "project_id": e["project_id"],
        "subcontractor_id": e["subcontractor_id"],
        "work_date": e["work_date"],
        "containment_intact": e["containment_intact"],
        "hepa_run_hours": e["hepa_run_hours"],
        "noise_db_max": e["noise_db_max"],
        "cleanup_completed": e["cleanup_completed"],
        "violation": e["violation"],
        "strike_applied": e["strike_applied"],
    }


def ser_inspection(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "work_phase_id": e["work_phase_id"],
        "type": e["type"],
        "result_notes": e["result_notes"],
        "resulted_at": e["resulted_at"],
        "status": e["status"],
    })
    return d


def ser_certificate(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "issued_at": e["issued_at"],
        "warranty_start": e["warranty_start"],
        "warranty_end": e["warranty_end"],
        "status": e["status"],
    })
    return d


def ser_warranty_claim(e):
    d = _common(e)
    d.update({
        "project_id": e["project_id"],
        "certificate_id": e["certificate_id"],
        "description": e["description"],
        "claimed_cents": e["claimed_cents"],
        "fresh_slab_moisture_lbs": e["fresh_slab_moisture_lbs"],
        "fresh_interior_rh_pct": e["fresh_interior_rh_pct"],
        "moisture_recurrence_confirmed": e["moisture_recurrence_confirmed"],
        "coverage_pct": e["coverage_pct"],
        "awarded_cents": e["awarded_cents"],
        "status": e["status"],
    })
    return d
