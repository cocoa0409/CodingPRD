"""Per-entity response views (PRD §2.5).

Permit, DamageLine and QualityInspection carry only `id` and `created_at` — they have
no `updated_at` and no `version` at all. Every other resource carries both. The
internal `_seq` insertion counter is never exposed.
"""

from services import aggregates
from services import posture as posture_service


def _base(row):
    return {"id": row["id"], "created_at": row["created_at"]}


def _versioned(row):
    view = _base(row)
    view["updated_at"] = row["updated_at"]
    view["version"] = row["version"]
    return view


def _num(value):
    """Decimal ratios are emitted as JSON numbers."""
    return float(value)


# --- StormEvent --------------------------------------------------------------

def storm_event(row):
    view = _versioned(row)
    view.update({
        "name": row["name"],
        "region_state_code": row["region_state_code"],
        "max_hail_size_mm": row["max_hail_size_mm"],
        "swath_area_km2": row["swath_area_km2"],
        "swath_confidence": row["swath_confidence"],
        "vehicle_population_estimate": row["vehicle_population_estimate"],
        "competitor_shop_count": row["competitor_shop_count"],
        "first_hail_at": row["first_hail_at"],
        "targeting_score": row["targeting_score"],
        "status": row["status"],
        "demobilized_at": row["demobilized_at"],
    })
    return view


# --- Facility ----------------------------------------------------------------

def facility(row):
    occupied, free, ratio = posture_service.staging_counters(row)
    view = _versioned(row)
    view.update({
        "storm_event_id": row["storm_event_id"],
        "name": row["name"],
        "state_code": row["state_code"],
        "address": row["address"],
        "staging_slot_count": row["staging_slot_count"],
        "pay_model": row["pay_model"],
        "status": row["status"],
        "posture": row["posture"],
        "staging_slots_occupied": occupied,
        "staging_slots_free": free,
        "staging_occupancy_ratio": _num(ratio),
        "billable_accrued_cents": aggregates.facility_billable_accrued_cents(row["id"]),
        "absorbed_rental_cents": aggregates.facility_absorbed_rental_cents(row["id"]),
        "warranty_counter": row["warranty_counter"],
        "commissioned_at": row["commissioned_at"],
    })
    return view


# --- Permit ------------------------------------------------------------------

def permit(row):
    view = _base(row)
    view.update({
        "facility_id": row["facility_id"],
        "permit_type": row["permit_type"],
        "issuing_jurisdiction": row["issuing_jurisdiction"],
        "status": row["status"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "decided_at": row["decided_at"],
    })
    return view


# --- Technician --------------------------------------------------------------

def technician(row):
    view = _versioned(row)
    view.update({
        "full_name": row["full_name"],
        "home_state_code": row["home_state_code"],
        "license_state_code": row["license_state_code"],
        "license_expires_at": row["license_expires_at"],
        "skill_tier": row["skill_tier"],
        "flat_split_pct": row["flat_split_pct"],
        "deployment_state": aggregates.technician_deployment_state(row["id"]),
        "accrued_pay_cents": aggregates.technician_accrued_pay_cents(row["id"]),
        "approved_ticket_count": aggregates.technician_approved_ticket_count(row["id"]),
    })
    return view


# --- HousingUnit -------------------------------------------------------------

def housing_unit(row, clock_date):
    view = _versioned(row)
    view.update({
        "facility_id": row["facility_id"],
        "label": row["label"],
        "bed_count": row["bed_count"],
        "nightly_rate_cents": row["nightly_rate_cents"],
        "occupied_beds": aggregates.housing_occupied_beds(row, clock_date),
        "bed_nights_committed": aggregates.housing_bed_nights_committed(row),
    })
    return view


# --- CrewDeployment ----------------------------------------------------------

def crew_deployment(row):
    view = _versioned(row)
    view.update({
        "technician_id": row["technician_id"],
        "facility_id": row["facility_id"],
        "housing_unit_id": row["housing_unit_id"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "pay_split_pct_snapshot": row["pay_split_pct_snapshot"],
        "status": row["status"],
        "actual_end_date": row["actual_end_date"],
        "effective_end_date": aggregates.effective_end_date(row),
    })
    return view


# --- Insurer -----------------------------------------------------------------

def insurer(row):
    view = _versioned(row)
    view.update({
        "name": row["name"],
        "naic_code": row["naic_code"],
        "direct_bill_enabled": row["direct_bill_enabled"],
        "outstanding_direct_bill_cents": aggregates.insurer_outstanding_direct_bill_cents(row["id"]),
        "settled_cents": aggregates.insurer_settled_cents(row["id"]),
        "active_rate_agreement_count": aggregates.insurer_active_rate_agreement_count(row["id"]),
    })
    return view


# --- RateAgreement -----------------------------------------------------------

def rate_agreement(row):
    view = _versioned(row)
    view.update({
        "insurer_id": row["insurer_id"],
        "storm_event_id": row["storm_event_id"],
        "effective_from": row["effective_from"],
        "matrix_rate_dime_cents": row["matrix_rate_dime_cents"],
        "matrix_rate_nickel_cents": row["matrix_rate_nickel_cents"],
        "matrix_rate_quarter_cents": row["matrix_rate_quarter_cents"],
        "matrix_rate_half_dollar_cents": row["matrix_rate_half_dollar_cents"],
        "labor_rate_cents_per_hour": row["labor_rate_cents_per_hour"],
        "panel_cap_cents": row["panel_cap_cents"],
        "admin_fee_pct": row["admin_fee_pct"],
        "admin_fee_cap_cents": row["admin_fee_cap_cents"],
        "supplement_auto_approve_pct": row["supplement_auto_approve_pct"],
        "rental_cap_days": row["rental_cap_days"],
        "rental_daily_rate_cents": row["rental_daily_rate_cents"],
        "status": row["status"],
        "activated_at": row["activated_at"],
    })
    return view


# --- Vehicle -----------------------------------------------------------------

def vehicle(row):
    view = _versioned(row)
    view.update({
        "facility_id": row["facility_id"],
        "insurer_id": row["insurer_id"],
        "pinned_rate_agreement_id": row["pinned_rate_agreement_id"],
        "vin": row["vin"],
        "model_year": row["model_year"],
        "make": row["make"],
        "model": row["model"],
        "acv_cents": row["acv_cents"],
        "owner_name": row["owner_name"],
        "rental_required": row["rental_required"],
        "matrix_variant_total_cents": row["matrix_variant_total_cents"],
        "conventional_variant_total_cents": row["conventional_variant_total_cents"],
        "pdr_feasible": row["pdr_feasible"],
        "triage_disposition": row["triage_disposition"],
        "approved_repair_cents": row["approved_repair_cents"],
        "approved_supplement_cents": aggregates.vehicle_approved_supplement_cents(row["id"]),
        "admin_fee_cents": row["admin_fee_cents"],
        "gross_billable_cents": row["gross_billable_cents"],
        "discount_cents": row["discount_cents"],
        "net_billable_cents": row["net_billable_cents"],
        "repair_status": row["repair_status"],
        "billing_status": row["billing_status"],
        "rework_count": row["rework_count"],
        "rental_opened_at": row["rental_opened_at"],
        "rental_closed_at": row["rental_closed_at"],
        "rental_days_billed": row["rental_days_billed"],
        "shop_absorbed_rental_cents": row["shop_absorbed_rental_cents"],
        "warranty_number": row["warranty_number"],
        "warranty_expires_at": row["warranty_expires_at"],
        "released_at": row["released_at"],
    })
    return view


# --- DamageLine --------------------------------------------------------------

def damage_line(row):
    view = _base(row)
    view.update({
        "vehicle_id": row["vehicle_id"],
        "panel_code": row["panel_code"],
        "dent_count": row["dent_count"],
        "dent_size_class": row["dent_size_class"],
        "aluminum": row["aluminum"],
        "r_and_i_hours": row["r_and_i_hours"],
        "oversize_dent_count": row["oversize_dent_count"],
        "conventional_labor_hours": row["conventional_labor_hours"],
        "conventional_paint_materials_cents": row["conventional_paint_materials_cents"],
        "pdr_line_cents": row["pdr_line_cents"],
        "conventional_line_cents": row["conventional_line_cents"],
        "capped": row["capped"],
        "routed_to": row["routed_to"],
    })
    return view


# --- WorkTicket --------------------------------------------------------------

def work_ticket(row):
    view = _versioned(row)
    view.update({
        "vehicle_id": row["vehicle_id"],
        "technician_id": row["technician_id"],
        "labor_units": row["labor_units"],
        "dents_repaired": row["dents_repaired"],
        "panels_worked": row["panels_worked"],
        "status": row["status"],
        "payable_flat_cents": row["payable_flat_cents"],
        "payable_pooled_cents": row["payable_pooled_cents"],
        "payable_cents": row["payable_cents"],
        "pay_model_applied": row["pay_model_applied"],
    })
    return view


# --- Supplement --------------------------------------------------------------

def supplement(row):
    view = _versioned(row)
    view.update({
        "vehicle_id": row["vehicle_id"],
        "rate_agreement_id": row["rate_agreement_id"],
        "supersedes_supplement_id": row["supersedes_supplement_id"],
        "reason_code": row["reason_code"],
        "requested_amount_cents": row["requested_amount_cents"],
        "counter_amount_cents": row["counter_amount_cents"],
        "approved_amount_cents": row["approved_amount_cents"],
        "round_index": row["round_index"],
        "status": row["status"],
        "decided_at": row["decided_at"],
    })
    return view


# --- QualityInspection -------------------------------------------------------

def quality_inspection(row):
    view = _base(row)
    view.update({
        "vehicle_id": row["vehicle_id"],
        "inspector_technician_id": row["inspector_technician_id"],
        "result": row["result"],
        "defect_panel_codes": list(row["defect_panel_codes"]),
        "rework_index": row["rework_index"],
        "inspected_at": row["inspected_at"],
    })
    return view
