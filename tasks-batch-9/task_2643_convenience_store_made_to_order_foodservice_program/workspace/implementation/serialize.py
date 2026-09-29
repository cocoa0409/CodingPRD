"""Per-entity JSON representations.

Field names and the presence/absence of updated_at + version follow
SCAFFOLD entities and PRD 2.6: ModifierOption, FuelTransaction, WasteLog and
TemperatureLog are append-only evidence and carry only id and created_at.
"""

from core import fmt_dt, fmt_ms, num_out


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": fmt_ms(rec["created_at"])}
    if versioned:
        out["updated_at"] = fmt_ms(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def store_out(rec):
    out = _common(rec)
    out.update({
        "store_code": rec["store_code"],
        "name": rec["name"],
        "is_fuel_site": rec["is_fuel_site"],
        "current_daypart": rec["current_daypart"],
        "daypart_epoch": rec["daypart_epoch"],
        "hot_case_slot_capacity": rec["hot_case_slot_capacity"],
        "hot_case_slots_used": rec["hot_case_slots_used"],
        "pickup_slot_capacity": rec["pickup_slot_capacity"],
        "waste_cost_cents_mtd": rec["waste_cost_cents_mtd"],
        "rework_waste_cents_mtd": rec["rework_waste_cents_mtd"],
    })
    return out


def holding_unit_out(rec):
    out = _common(rec)
    out.update({
        "store_id": rec["store_id"],
        "unit_code": rec["unit_code"],
        "unit_type": rec["unit_type"],
        "min_temp_f": num_out(rec["min_temp_f"]),
        "max_temp_f": num_out(rec["max_temp_f"]),
        "slot_count": rec["slot_count"],
        "status": rec["status"],
        "consecutive_out_of_range_count": rec["consecutive_out_of_range_count"],
        "last_temp_log_at": fmt_dt(rec["last_temp_log_at"]),
    })
    return out


def menu_item_out(rec):
    out = _common(rec)
    out.update({
        "sku": rec["sku"],
        "name": rec["name"],
        "station": rec["station"],
        "fulfillment_mode": rec["fulfillment_mode"],
        "base_price_cents": rec["base_price_cents"],
        "unit_food_cost_cents": rec["unit_food_cost_cents"],
        "prep_seconds": rec["prep_seconds"],
        "bake_minutes": rec["bake_minutes"],
        "hold_minutes": rec["hold_minutes"],
        "valid_dayparts": list(rec["valid_dayparts"]),
        "included_premium_count": rec["included_premium_count"],
        "is_catering_eligible": rec["is_catering_eligible"],
    })
    return out


def modifier_option_out(rec):
    out = _common(rec, versioned=False)
    out.update({
        "menu_item_id": rec["menu_item_id"],
        "code": rec["code"],
        "modifier_class": rec["modifier_class"],
        "price_delta_cents": rec["price_delta_cents"],
        "is_premium": rec["is_premium"],
        "max_qty": rec["max_qty"],
    })
    return out


def promotion_rule_out(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "kind": rec["kind"],
        "discount_kind": rec["discount_kind"],
        "discount_bp": rec["discount_bp"],
        "discount_cents": rec["discount_cents"],
        "max_discount_cents": rec["max_discount_cents"],
        "min_food_subtotal_cents": rec["min_food_subtotal_cents"],
        "requires_fuel_gallons": num_out(rec["requires_fuel_gallons"]),
        "target_station": rec["target_station"],
        "valid_dayparts": list(rec["valid_dayparts"]),
        "stacking_rank": rec["stacking_rank"],
        "status": rec["status"],
    })
    return out


def loyalty_account_out(rec):
    out = _common(rec)
    out.update({
        "member_code": rec["member_code"],
        "email": rec["email"],
        "points_balance": rec["points_balance"],
        "lifetime_points_earned": rec["lifetime_points_earned"],
        "lifetime_points_redeemed": rec["lifetime_points_redeemed"],
        "points_reversed_total": rec["points_reversed_total"],
        "tier": rec["tier"],
    })
    return out


def fuel_transaction_out(rec):
    out = _common(rec, versioned=False)
    out.update({
        "loyalty_account_id": rec["loyalty_account_id"],
        "gallons": num_out(rec["gallons"]),
        "price_per_gallon_cents": rec["price_per_gallon_cents"],
        "occurred_at": fmt_dt(rec["occurred_at"]),
        "fuel_spend_cents": rec["fuel_spend_cents"],
    })
    return out


def staffing_plan_out(rec):
    out = _common(rec)
    out.update({
        "store_id": rec["store_id"],
        "service_date": rec["service_date"],
        "daypart": rec["daypart"],
        "forecast_txn_count": rec["forecast_txn_count"],
        "mto_share_bp": rec["mto_share_bp"],
        "planned_labor_minutes": rec["planned_labor_minutes"],
        "peak_multiplier_bp": rec["peak_multiplier_bp"],
        "status": rec["status"],
    })
    return out


def production_batch_out(rec):
    out = _common(rec)
    out.update({
        "store_id": rec["store_id"],
        "menu_item_id": rec["menu_item_id"],
        "holding_unit_id": rec["holding_unit_id"],
        "slot_index": rec["slot_index"],
        "planned_qty": rec["planned_qty"],
        "bake_start_at": fmt_dt(rec["bake_start_at"]),
        "occupancy_end_at": fmt_dt(rec["occupancy_end_at"]),
        "baked_qty": rec["baked_qty"],
        "remaining_qty": rec["remaining_qty"],
        "reserved_qty": rec["reserved_qty"],
        "sold_qty": rec["sold_qty"],
        "discarded_qty": rec["discarded_qty"],
        "hold_started_at": fmt_dt(rec["hold_started_at"]),
        "hold_expires_at": fmt_dt(rec["hold_expires_at"]),
        "status": rec["status"],
    })
    return out


def waste_log_out(rec):
    out = _common(rec, versioned=False)
    out.update({
        "production_batch_id": rec["production_batch_id"],
        "qty": rec["qty"],
        "reason": rec["reason"],
        "food_cost_cents": rec["food_cost_cents"],
        "retail_value_cents": rec["retail_value_cents"],
        "logged_by_user_id": rec["logged_by_user_id"],
        "daypart_epoch": rec["daypart_epoch"],
    })
    return out


def temperature_log_out(rec):
    out = _common(rec, versioned=False)
    out.update({
        "holding_unit_id": rec["holding_unit_id"],
        "reading_f": num_out(rec["reading_f"]),
        "in_range": rec["in_range"],
        "logged_by_user_id": rec["logged_by_user_id"],
        "recorded_at": fmt_dt(rec["recorded_at"]),
    })
    return out


def corrective_action_out(rec):
    out = _common(rec)
    out.update({
        "temperature_log_id": rec["temperature_log_id"],
        "action_taken": rec["action_taken"],
        "status": rec["status"],
        "opened_by_user_id": rec["opened_by_user_id"],
        "verified_by_user_id": rec["verified_by_user_id"],
        "verified_at": fmt_dt(rec["verified_at"]),
    })
    return out


def order_out(rec):
    out = _common(rec)
    out.update({
        "store_id": rec["store_id"],
        "loyalty_account_id": rec["loyalty_account_id"],
        "channel": rec["channel"],
        "production_status": rec["production_status"],
        "settlement_status": rec["settlement_status"],
        "pickup_window_start": fmt_dt(rec["pickup_window_start"]),
        "pickup_window_end": fmt_dt(rec["pickup_window_end"]),
        "daypart_at_placement": rec["daypart_at_placement"],
        "subtotal_gross_cents": rec["subtotal_gross_cents"],
        "promo_discount_cents": rec["promo_discount_cents"],
        "service_fee_cents": rec["service_fee_cents"],
        "total_cents": rec["total_cents"],
        "applied_promotion_id": rec["applied_promotion_id"],
        "points_provisional": rec["points_provisional"],
        "points_final": rec["points_final"],
        "expected_ready_at": fmt_dt(rec["expected_ready_at"]),
        "placed_at": fmt_dt(rec["placed_at"]),
        "ready_at": fmt_dt(rec["ready_at"]),
        "rework_count": rec["rework_count"],
        "tender_type": rec["tender_type"],
    })
    return out


def order_line_out(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "menu_item_id": rec["menu_item_id"],
        "qty": rec["qty"],
        "modifiers": [
            {"modifier_option_id": m["modifier_option_id"], "qty": m["qty"]}
            for m in rec["modifiers"]
        ],
        "station": rec["station"],
        "unit_price_cents": rec["unit_price_cents"],
        "premium_surcharge_cents": rec["premium_surcharge_cents"],
        "line_gross_cents": rec["line_gross_cents"],
        "line_discount_cents": rec["line_discount_cents"],
        "line_net_cents": rec["line_net_cents"],
        "fulfillment_batch_id": rec["fulfillment_batch_id"],
        "reserved_qty": rec["reserved_qty"],
    })
    return out


def kitchen_ticket_out(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "store_id": rec["store_id"],
        "station": rec["station"],
        "status": rec["status"],
        "sequence_position": rec["sequence_position"],
        "prep_seconds": rec["prep_seconds"],
        "lead_seconds": rec["lead_seconds"],
        "promised_ready_at": fmt_dt(rec["promised_ready_at"]),
        "started_by_user_id": rec["started_by_user_id"],
        "completed_by_user_id": rec["completed_by_user_id"],
        "rework_count": rec["rework_count"],
    })
    return out
