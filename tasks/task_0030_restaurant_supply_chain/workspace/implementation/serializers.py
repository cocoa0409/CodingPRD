"""Entity-to-JSON serialization helpers."""

import clock


def _ts(dt):
    return clock.iso_format(dt) if dt is not None else None


def store_dict(s):
    return {
        "id": s["id"],
        "store_code": s["store_code"],
        "name": s["name"],
        "temperature_zone": s["temperature_zone"],
        "catalog_permission": list(s["catalog_permission"]),
        "order_window_open_minute": s["order_window_open_minute"],
        "order_window_close_minute": s["order_window_close_minute"],
        "cutoff_minutes_before_close": s["cutoff_minutes_before_close"],
        "low_amount_bypass_cents": s["low_amount_bypass_cents"],
        "avg_daily_sales_cents": s["avg_daily_sales_cents"],
        "status": s["status"],
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }


def recipe_dict(r):
    return {
        "id": r["id"],
        "recipe_code": r["recipe_code"],
        "name": r["name"],
        "temperature_zone": r["temperature_zone"],
        "shelf_life_hours": r["shelf_life_hours"],
        "production_minutes_per_unit": r["production_minutes_per_unit"],
        "equipment_class": r["equipment_class"],
        "unit_price_cents": r["unit_price_cents"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def ingredient_dict(i):
    return {
        "id": i["id"],
        "sku": i["sku"],
        "name": i["name"],
        "unit": i["unit"],
        "shelf_life_hours": i["shelf_life_hours"],
        "unit_cost_cents": i["unit_cost_cents"],
        "created_at": _ts(i["created_at"]),
        "updated_at": _ts(i["updated_at"]),
        "version": i["version"],
    }


def recipe_ingredient_dict(ri):
    return {
        "id": ri["id"],
        "recipe_id": ri["recipe_id"],
        "ingredient_id": ri["ingredient_id"],
        "quantity_per_unit": ri["quantity_per_unit"],
        "created_at": _ts(ri["created_at"]),
    }


def order_line_dict(ol):
    return {
        "id": ol["id"],
        "store_order_id": ol["store_order_id"],
        "recipe_id": ol["recipe_id"],
        "quantity": ol["quantity"],
        "line_value_cents": ol["line_value_cents"],
        "created_at": _ts(ol["created_at"]),
    }


def store_order_dict(o):
    return {
        "id": o["id"],
        "store_id": o["store_id"],
        "target_delivery_date": o["target_delivery_date"],
        "submitted_at": _ts(o["submitted_at"]),
        "cancelled_at": _ts(o["cancelled_at"]),
        "total_units": o["total_units"],
        "total_value_cents": o["total_value_cents"],
        "consolidation_batch_id": o["consolidation_batch_id"],
        "status": o["status"],
        "created_at": _ts(o["created_at"]),
        "updated_at": _ts(o["updated_at"]),
        "version": o["version"],
    }


def production_batch_dict(b):
    return {
        "id": b["id"],
        "recipe_id": b["recipe_id"],
        "planned_units": b["planned_units"],
        "forecast_units": b["forecast_units"],
        "equipment_minutes": b["equipment_minutes"],
        "scheduled_start_at": _ts(b["scheduled_start_at"]),
        "scheduled_end_at": _ts(b["scheduled_end_at"]),
        "produced_at": _ts(b["produced_at"]),
        "expires_at": _ts(b["expires_at"]),
        "target_delivery_date": b["target_delivery_date"],
        "status": b["status"],
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def vehicle_dict(v):
    return {
        "id": v["id"],
        "vehicle_code": v["vehicle_code"],
        "capacity_units": v["capacity_units"],
        "temperature_zones": list(v["temperature_zones"]),
        "status": v["status"],
        "created_at": _ts(v["created_at"]),
        "updated_at": _ts(v["updated_at"]),
        "version": v["version"],
    }


def delivery_route_dict(r):
    return {
        "id": r["id"],
        "vehicle_id": r["vehicle_id"],
        "driver_user_id": r["driver_user_id"],
        "planned_stops": [_serialize_stop(s) for s in r["planned_stops"]],
        "total_units_loaded": r["total_units_loaded"],
        "required_zones": list(r["required_zones"]),
        "target_delivery_date": r["target_delivery_date"],
        "dispatched_at": _ts(r["dispatched_at"]),
        "completed_at": _ts(r["completed_at"]),
        "exception_reason": r["exception_reason"],
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def _serialize_stop(s):
    return {
        "store_id": s["store_id"],
        "time_window_start": _ts(s["time_window_start"]),
        "time_window_end": _ts(s["time_window_end"]),
        "batch_ids": list(s["batch_ids"]),
    }


def inventory_batch_dict(b):
    return {
        "id": b["id"],
        "store_id": b["store_id"],
        "recipe_id": b["recipe_id"],
        "production_batch_id": b["production_batch_id"],
        "quantity_on_hand": b["quantity_on_hand"],
        "received_at": _ts(b["received_at"]),
        "expires_at": _ts(b["expires_at"]),
        "alert_tier": b["alert_tier"],
        "status": b["status"],
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def replenishment_rule_dict(r):
    return {
        "id": r["id"],
        "store_id": r["store_id"],
        "recipe_id": r["recipe_id"],
        "safety_stock_units": r["safety_stock_units"],
        "replenish_to_units": r["replenish_to_units"],
        "cycle_hours": r["cycle_hours"],
        "velocity_multiplier": r["velocity_multiplier"],
        "last_evaluated_at": _ts(r["last_evaluated_at"]),
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def loss_record_dict(lr):
    return {
        "id": lr["id"],
        "store_id": lr["store_id"],
        "inventory_batch_id": lr["inventory_batch_id"],
        "quantity_lost": lr["quantity_lost"],
        "cause": lr["cause"],
        "responsibility_user_id": lr["responsibility_user_id"],
        "financial_impact_cents": lr["financial_impact_cents"],
        "is_abnormal": lr["is_abnormal"],
        "investigation_status": lr["investigation_status"],
        "status": lr["status"],
        "created_at": _ts(lr["created_at"]),
        "updated_at": _ts(lr["updated_at"]),
        "version": lr["version"],
    }


def audit_log_entry_dict(a):
    return {
        "id": a["id"],
        "target_type": a["target_type"],
        "target_id": a["target_id"],
        "action": a["action"],
        "actor_role": a["actor_role"],
        "actor_user_id": a["actor_user_id"],
        "payload": a["payload"],
        "external_systems": list(a["external_systems"]),
        "created_at": _ts(a["created_at"]),
    }
