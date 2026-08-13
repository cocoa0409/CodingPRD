"""Entity serializers — output exactly the scaffold-declared fields.
Computed fields are derived via services at read time."""

import services as svc
from util import fnum, iso_z


def _common(rec):
    return {
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _dt(value):
    return iso_z(value) if value is not None else None


def recipe_out(r):
    out = {
        "id": r["id"],
        "name": r["name"],
        "product_style": r["product_style"],
        "base_batch_yield_units": r["base_batch_yield_units"],
        "portion_weight_g": fnum(r["portion_weight_g"]),
        "shelf_life_days": r["shelf_life_days"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def component_out(c):
    out = {
        "id": c["id"],
        "recipe_id": c["recipe_id"],
        "parent_component_id": c["parent_component_id"],
        "component_name": c["component_name"],
        "component_type": c["component_type"],
        "quantity_per_base_batch": fnum(c["quantity_per_base_batch"]),
        "unit_of_measure": c["unit_of_measure"],
        "scale_exponent": fnum(c["scale_exponent"]),
        "allergen_tag": c["allergen_tag"],
    }
    out.update(_common(c))
    return out


def customer_out(c):
    out = {
        "id": c["id"],
        "name": c["name"],
        "billing_method": c["billing_method"],
        "case_rate_cents": c["case_rate_cents"],
        "kg_rate_cents": c["kg_rate_cents"],
        "requires_allergen_changeover": c["requires_allergen_changeover"],
        "base_changeover_minutes": c["base_changeover_minutes"],
    }
    out.update(_common(c))
    return out


def order_out(o):
    out = {
        "id": o["id"],
        "recipe_id": o["recipe_id"],
        "copack_customer_id": o["copack_customer_id"],
        "pack_format": o["pack_format"],
        "units_planned": o["units_planned"],
        "due_at": _dt(o["due_at"]),
        "units_packed_total": svc.order_units_packed(o),
        "releasable_cases": svc.order_releasable_cases(o),
        "billed_amount_cents": svc.order_billed_amount_cents(o),
        "status": o["status"],
    }
    out.update(_common(o))
    return out


def batch_out(b):
    y = svc.batch_yield_pct(b)
    out = {
        "id": b["id"],
        "order_id": b["order_id"],
        "units_planned": b["units_planned"],
        "cooked_mass_kg": fnum(b["cooked_mass_kg"]) if b["cooked_mass_kg"] is not None else None,
        "units_packed_total": svc.batch_units_packed(b),
        "yield_pct": fnum(y) if y is not None else None,
        "status": b["status"],
        "hold_origin_state": b["hold_origin_state"],
        "hold_reason": b["hold_reason"],
    }
    out.update(_common(b))
    return out


def cell_out(c):
    out = {
        "id": c["id"],
        "cell_code": c["cell_code"],
        "capacity_kg": c["capacity_kg"],
        "min_load_kg": c["min_load_kg"],
        "pull_down_kg_per_hour": c["pull_down_kg_per_hour"],
        "sanitation_minutes": c["sanitation_minutes"],
        "status": svc.cell_status(c),
    }
    out.update(_common(c))
    return out


def cycle_out(c):
    out = {
        "id": c["id"],
        "batch_id": c["batch_id"],
        "cell_id": c["cell_id"],
        "load_kg": c["load_kg"],
        "entry_temp_c": fnum(c["entry_temp_c"]),
        "planned_start": _dt(c["planned_start"]),
        "required_hours": c["required_hours"],
        "planned_end": _dt(c["planned_end"]),
        "actual_end": _dt(c["actual_end"]),
        "final_core_temp_c": fnum(c["final_core_temp_c"]) if c["final_core_temp_c"] is not None else None,
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def line_out(l):
    out = {
        "id": l["id"],
        "line_code": l["line_code"],
        "line_type": l["line_type"],
        "rate_units_per_minute": l["rate_units_per_minute"],
        "supported_film_type": l["supported_film_type"],
    }
    out.update(_common(l))
    return out


def run_out(r):
    out = {
        "id": r["id"],
        "line_id": r["line_id"],
        "batch_id": r["batch_id"],
        "film_lot_id": r["film_lot_id"],
        "planned_start": _dt(r["planned_start"]),
        "units_planned": r["units_planned"],
        "duration_minutes": r["duration_minutes"],
        "planned_end": _dt(r["planned_end"]),
        "reserved_film_m": r["reserved_film_m"],
        "units_packed": r["units_packed"],
        "film_meters_consumed": r["film_meters_consumed"],
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def film_lot_out(l):
    received, reserved, consumed, available = svc.film_meters(l)
    out = {
        "id": l["id"],
        "film_type": l["film_type"],
        "rolls_received": l["rolls_received"],
        "meters_per_roll": l["meters_per_roll"],
        "meters_received": received,
        "meters_reserved": reserved,
        "meters_consumed": consumed,
        "meters_available": available,
        "status": l["status"],
    }
    out.update(_common(l))
    return out


def check_out(c):
    """CCPCheck is append-only: id + created_at only, no updated_at/version (PRD §2.5)."""
    return {
        "id": c["id"],
        "batch_id": c["batch_id"],
        "check_type": c["check_type"],
        "test_piece_detected": c["test_piece_detected"],
        "measured_size_mm": fnum(c["measured_size_mm"]) if c["measured_size_mm"] is not None else None,
        "result": c["result"],
        "performed_by_user_id": c["performed_by_user_id"],
        "performed_at": _dt(c["performed_at"]),
        "created_at": c["created_at"],
    }


def slot_out(s):
    out = {
        "id": s["id"],
        "slot_code": s["slot_code"],
        "zone": s["zone"],
        "temperature_class": s["temperature_class"],
        "capacity_cases": s["capacity_cases"],
        "occupied_cases": svc.slot_occupied(s["id"]),
    }
    out.update(_common(s))
    return out


def lot_out(l):
    provisional, final = svc.lot_expiry_dates(l)
    out = {
        "id": l["id"],
        "batch_id": l["batch_id"],
        "slot_id": l["slot_id"],
        "pack_format": l["pack_format"],
        "cases_produced": l["cases_produced"],
        "net_weight_kg": fnum(l["net_weight_kg"]),
        "stored_cases": l["stored_cases"],
        "cases_on_hand": svc.lot_cases_on_hand(l),
        "cases_shipped": l["cases_shipped"],
        "provisional_expiry_date": provisional,
        "final_expiry_date": final,
        "valid_complaint_count": svc.lot_valid_complaint_count(l),
        "release_status": l["release_status"],
    }
    out.update(_common(l))
    return out


def complaint_out(c):
    out = {
        "id": c["id"],
        "lot_id": c["lot_id"],
        "complaint_type": c["complaint_type"],
        "units_affected": c["units_affected"],
        "reported_by_user_id": c["reported_by_user_id"],
        "reported_at": _dt(c["reported_at"]),
        "days_before_expiry": svc.complaint_days_before_expiry(c),
        "status": c["status"],
    }
    out.update(_common(c))
    return out
