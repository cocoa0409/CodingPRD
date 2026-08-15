"""Entity -> JSON dict serializers. Datetimes are stored internally as aware
UTC datetimes and serialized as ISO 8601 with three fractional digits."""
from db import iso


def product_json(p):
    return {
        "id": p["id"],
        "sku_code": p["sku_code"],
        "name": p["name"],
        "product_type": p["product_type"],
        "brand": p["brand"],
        "customer_name": p["customer_name"],
        "base_price_cents": p["base_price_cents"],
        "unit_weight_grams": p["unit_weight_grams"],
        "shelf_life_days": p["shelf_life_days"],
        "packaging_component_id": p["packaging_component_id"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def recipe_json(r):
    return {
        "id": r["id"],
        "product_id": r["product_id"],
        "name": r["name"],
        "shape_code": r["shape_code"],
        "cook_temp_min_c": r["cook_temp_min_c"],
        "cook_temp_max_c": r["cook_temp_max_c"],
        "temper_exit_min_c": r["temper_exit_min_c"],
        "temper_exit_max_c": r["temper_exit_max_c"],
        "allergens": list(r["allergens"]),
        "standard_yield_pct": r["standard_yield_pct"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def gift_component_json(g):
    # Gift BOM rows are immutable: id and created_at only (PRD §2.4).
    return {
        "id": g["id"],
        "gift_product_id": g["gift_product_id"],
        "component_product_id": g["component_product_id"],
        "qty_per_set": g["qty_per_set"],
        "created_at": iso(g["created_at"]),
    }


def packaging_component_json(c):
    return {
        "id": c["id"],
        "sku_code": c["sku_code"],
        "name": c["name"],
        "units_per_component": c["units_per_component"],
        "lead_time_days": c["lead_time_days"],
        "qty_on_hand": c["qty_on_hand"],
        "qty_reserved": c["qty_reserved"],
        "qty_available": c["qty_available"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def purchase_order_json(po):
    return {
        "id": po["id"],
        "component_id": po["component_id"],
        "order_qty": po["order_qty"],
        "ordered_at": iso(po["ordered_at"]),
        "due_at": iso(po["due_at"]),
        "received_at": iso(po["received_at"]),
        "status": po["status"],
        "created_at": iso(po["created_at"]),
        "updated_at": iso(po["updated_at"]),
        "version": po["version"],
    }


def mold_json(m):
    return {
        "id": m["id"],
        "shape_code": m["shape_code"],
        "cavity_count": m["cavity_count"],
        "status": m["status"],
        "created_at": iso(m["created_at"]),
        "updated_at": iso(m["updated_at"]),
        "version": m["version"],
    }


def line_json(l):
    return {
        "id": l["id"],
        "name": l["name"],
        "current_mold_id": l["current_mold_id"],
        "cleared_allergens": list(l["cleared_allergens"]),
        "status": l["status"],
        "created_at": iso(l["created_at"]),
        "updated_at": iso(l["updated_at"]),
        "version": l["version"],
    }


def changeover_json(c):
    return {
        "id": c["id"],
        "line_id": c["line_id"],
        "changeover_type": c["changeover_type"],
        "to_mold_id": c["to_mold_id"],
        "target_allergens": (list(c["target_allergens"]) if c["target_allergens"] is not None else None),
        "swab_recorded_by": c["swab_recorded_by"],
        "swab_passed": c["swab_passed"],
        "qa_released_by": c["qa_released_by"],
        "status": c["status"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def window_json(w):
    return {
        "id": w["id"],
        "season_code": w["season_code"],
        "build_start": iso(w["build_start"]),
        "build_end": iso(w["build_end"]),
        "ship_start": iso(w["ship_start"]),
        "ship_end": iso(w["ship_end"]),
        "target_units": w["target_units"],
        "markdown_tiers": [dict(t) for t in w["markdown_tiers"]],
        "confirmed_build_units": w["confirmed_build_units"],
        "projected_build_units": w["projected_build_units"],
        "coverage_pct": w["coverage_pct"],
        "shortfall": w["shortfall"],
        "status": w["status"],
        "created_at": iso(w["created_at"]),
        "updated_at": iso(w["updated_at"]),
        "version": w["version"],
    }


def run_json(r):
    return {
        "id": r["id"],
        "window_id": r["window_id"],
        "product_id": r["product_id"],
        "recipe_id": r["recipe_id"],
        "line_id": r["line_id"],
        "run_type": r["run_type"],
        "planned_units": r["planned_units"],
        "scheduled_start": iso(r["scheduled_start"]),
        "scheduled_end": iso(r["scheduled_end"]),
        "source_lot_id": r["source_lot_id"],
        "rework_qty": r["rework_qty"],
        "packaging_reserved_qty": r["packaging_reserved_qty"],
        "output_units": r["output_units"],
        "expected_output_units": r["expected_output_units"],
        "created_lot_id": r["created_lot_id"],
        "status": r["status"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def lot_json(l):
    return {
        "id": l["id"],
        "product_id": l["product_id"],
        "run_id": l["run_id"],
        "mfg_date": iso(l["mfg_date"]),
        "expiry_date": iso(l["expiry_date"]),
        "qty_on_hand": l["qty_on_hand"],
        "qty_reserved_rework": l["qty_reserved_rework"],
        "qty_scrapped": l["qty_scrapped"],
        "unit_price_cents": l["unit_price_cents"],
        "quality_status": l["quality_status"],
        "status": l["status"],
        "created_at": iso(l["created_at"]),
        "updated_at": iso(l["updated_at"]),
        "version": l["version"],
    }


def hold_json(h):
    return {
        "id": h["id"],
        "lot_id": h["lot_id"],
        "defect_type": h["defect_type"],
        "affected_units": h["affected_units"],
        "lot_qty_at_open": h["lot_qty_at_open"],
        "defect_rate_pct": h["defect_rate_pct"],
        "opened_by": h["opened_by"],
        "disposition_by": h["disposition_by"],
        "status": h["status"],
        "created_at": iso(h["created_at"]),
        "updated_at": iso(h["updated_at"]),
        "version": h["version"],
    }
