"""Public serializers — produce the exact field set per entity (PRD §1.1, §2.4).

ItemModifier and TipAllocation carry only id + created_at (PRD §2.4).
Every other entity carries id, created_at, updated_at, version.
"""
import db


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _common_immutable(rec):
    return {"id": rec["id"], "created_at": rec["created_at"]}


def restaurant(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "tax_rate_bps": rec["tax_rate_bps"],
        "large_party_threshold": rec["large_party_threshold"],
        "auto_gratuity_bps": rec["auto_gratuity_bps"],
        "comp_cap_bps": rec["comp_cap_bps"],
        "min_rest_minutes": rec["min_rest_minutes"],
        "current_utc": db.iso_ms(rec["current_utc"]),
    })
    return out


def menu_item(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "name": rec["name"],
        "station": rec["station"],
        "base_price_cents": rec["base_price_cents"],
        "happy_hour_price_cents": rec["happy_hour_price_cents"],
        "initial_available_count": rec["initial_available_count"],
        "available_count": rec["available_count"],
        "is_86": rec["available_count"] == 0,
    })
    return out


def happy_hour_window(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "day_of_week": rec["day_of_week"],
        "start_minute": rec["start_minute"],
        "end_minute": rec["end_minute"],
    })
    return out


def dining_table(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "table_number": rec["table_number"],
        "capacity": rec["capacity"],
        "occupancy_status": rec["occupancy_status"],
    })
    return out


def waitlist_entry(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "party_name": rec["party_name"],
        "party_size": rec["party_size"],
        "status": rec["status"],
        "quoted_at": db.iso_ms(rec["quoted_at"]),
        "seating_id": rec["seating_id"],
    })
    return out


def seating(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "table_id": rec["table_id"],
        "waitlist_entry_id": rec["waitlist_entry_id"],
        "party_size": rec["party_size"],
        "status": rec["status"],
        "seated_at": db.iso_ms(rec["seated_at"]),
        "cleared_at": db.iso_ms(rec["cleared_at"]),
    })
    return out


def check(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "seating_id": rec["seating_id"],
        "server_staff_id": rec["server_staff_id"],
        "party_size": rec["party_size"],
        "status": rec["status"],
        "provisional_subtotal_cents": rec["provisional_subtotal_cents"],
        "final_subtotal_cents": rec["final_subtotal_cents"],
        "comp_total_cents": rec["comp_total_cents"],
        "auto_gratuity_cents": rec["auto_gratuity_cents"],
        "tax_cents": rec["tax_cents"],
        "total_due_cents": rec["total_due_cents"],
        "amount_paid_cents": rec["amount_paid_cents"],
        "tip_cents": rec["tip_cents"],
    })
    return out


def course(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "check_id": rec["check_id"],
        "course_number": rec["course_number"],
        "status": rec["status"],
        "fired_at": db.iso_ms(rec["fired_at"]),
    })
    return out


def order_item(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "course_id": rec["course_id"],
        "menu_item_id": rec["menu_item_id"],
        "quantity": rec["quantity"],
        "status": rec["status"],
        "unit_price_cents": rec["unit_price_cents"],
        "line_subtotal_cents": rec["line_subtotal_cents"],
        "comp_amount_cents": rec["comp_amount_cents"],
    })
    return out


def item_modifier(rec):
    out = _common_immutable(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "order_item_id": rec["order_item_id"],
        "name": rec["name"],
        "surcharge_cents": rec["surcharge_cents"],
    })
    return out


def staff_member(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "name": rec["name"],
        "role": rec["role"],
        "tip_weight_bps": rec["tip_weight_bps"],
    })
    return out


def staff_shift(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "staff_id": rec["staff_id"],
        "business_date": rec["business_date"],
        "clock_in_minute": rec["clock_in_minute"],
        "clock_out_minute": rec["clock_out_minute"],
        "hours_worked_x100": rec["hours_worked_x100"],
    })
    return out


def tip_pool(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "business_date": rec["business_date"],
        "distribution_mode": rec["distribution_mode"],
        "status": rec["status"],
        "pooled_cents": rec["pooled_cents"],
        "distributed_cents": rec["distributed_cents"],
    })
    return out


def tip_allocation(rec):
    out = _common_immutable(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "tip_pool_id": rec["tip_pool_id"],
        "staff_shift_id": rec["staff_shift_id"],
        "amount_cents": rec["amount_cents"],
    })
    return out


def payment(rec):
    out = _common(rec)
    out.update({
        "restaurant_id": rec["restaurant_id"],
        "check_id": rec["check_id"],
        "amount_cents": rec["amount_cents"],
        "tip_cents": rec["tip_cents"],
        "method": rec["method"],
        "status": rec["status"],
    })
    return out
