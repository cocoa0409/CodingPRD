"""Entity -> public JSON serialization.

Each serializer returns the field set the PRD/SCAFFOLD declares for that entity,
including computed fields, and the appropriate common fields. Full-field
entities expose id/created_at/updated_at/version; append-only records expose
only id/created_at.
"""
import db


def _full_common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _append_common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }


def customer(rec):
    out = _full_common(rec)
    out.update({
        "name": rec["name"],
        "code": rec["code"],
        "owns_components": rec["owns_components"],
    })
    return out


def component(rec):
    out = _full_common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "sku": rec["sku"],
        "name": rec["name"],
        "kind": rec["kind"],
        "allergens": list(rec["allergens"]),
        "customer_owned": rec["customer_owned"],
        "on_hand_qty": rec["on_hand_qty"],
        "reserved_qty": rec["reserved_qty"],
    })
    return out


def component_lot(rec):
    out = _full_common(rec)
    out.update({
        "component_id": rec["component_id"],
        "supplier_lot_code": rec["supplier_lot_code"],
        "received_qty": rec["received_qty"],
        "remaining_qty": rec["remaining_qty"],
        "expiration_date": rec["expiration_date"],
        "status": rec["status"],
    })
    return out


def recipe(rec):
    out = _full_common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "name": rec["name"],
        "target_fill_weight_g": rec["target_fill_weight_g"],
        "fill_tolerance_pct": rec["fill_tolerance_pct"],
        "shelf_life_days": rec["shelf_life_days"],
        "allergen_profile": list(rec["allergen_profile"]),
        "status": rec["status"],
    })
    return out


def bom_line(rec):
    out = _full_common(rec)
    out.update({
        "recipe_id": rec["recipe_id"],
        "component_id": rec["component_id"],
        "qty_per_unit": rec["qty_per_unit"],
        "scrap_factor_pct": rec["scrap_factor_pct"],
    })
    return out


def production_line(rec):
    out = _full_common(rec)
    out.update({
        "name": rec["name"],
        "rated_units_per_hour": rec["rated_units_per_hour"],
        "changeover_minutes": rec["changeover_minutes"],
        "current_allergen_residue": list(rec["current_allergen_residue"]),
    })
    return out


def crew(rec):
    out = _full_common(rec)
    out.update({
        "name": rec["name"],
        "rest_buffer_minutes": rec["rest_buffer_minutes"],
    })
    return out


def production_run(rec):
    out = _full_common(rec)
    out.update({
        "recipe_id": rec["recipe_id"],
        "line_id": rec["line_id"],
        "crew_id": rec["crew_id"],
        "planned_units": rec["planned_units"],
        "scheduled_start": rec["scheduled_start"],
        "scheduled_end": rec["scheduled_end"],
        "actual_units_good": rec["actual_units_good"],
        "actual_units_scrapped": rec["actual_units_scrapped"],
        "lot_code": rec["lot_code"],
        "pack_date": rec["pack_date"],
        "fg_expiration_date": rec["fg_expiration_date"],
        "run_rate_units_per_hour": rec["run_rate_units_per_hour"],
        "status": rec["status"],
    })
    return out


def lot_consumption(rec):
    out = _append_common(rec)
    out.update({
        "production_run_id": rec["production_run_id"],
        "component_lot_id": rec["component_lot_id"],
        "bom_line_id": rec["bom_line_id"],
        "consumed_qty": rec["consumed_qty"],
        "customer_owned": rec["customer_owned"],
    })
    return out


def checkweigh_sample(rec):
    out = _append_common(rec)
    out.update({
        "production_run_id": rec["production_run_id"],
        "measured_weight_g": rec["measured_weight_g"],
        "verdict": rec["verdict"],
    })
    return out


def cmr_ledger_entry(rec):
    out = _append_common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "component_id": rec["component_id"],
        "production_run_id": rec["production_run_id"],
        "delta_qty": rec["delta_qty"],
        "reason": rec["reason"],
    })
    return out


def sanitation_event(rec):
    out = _append_common(rec)
    out.update({
        "line_id": rec["line_id"],
        "cleared_allergens": list(rec["cleared_allergens"]),
    })
    return out
