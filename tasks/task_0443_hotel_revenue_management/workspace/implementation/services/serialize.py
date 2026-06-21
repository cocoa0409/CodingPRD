"""Output projection: convert internal records to API-facing dicts.

Internal records carry helper keys (e.g. stay_date_key, _seq, *_for_calc) that
must not leak into responses. Each serializer emits exactly the entity fields
declared in scaffold §1.1.
"""
from services.calc import recompute_availability


def ser_property(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "total_rooms": p["total_rooms"],
        "overbooking_limit_pct": p["overbooking_limit_pct"],
        "currency": p["currency"],
        "occupancy_pct": p["occupancy_pct"],
        "adr": p["adr"],
        "revpar": p["revpar"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_room_type(r):
    return {
        "id": r["id"],
        "property_id": r["property_id"],
        "code": r["code"],
        "name": r["name"],
        "physical_rooms": r["physical_rooms"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_rate_plan(p):
    return {
        "id": p["id"],
        "room_type_id": p["room_type_id"],
        "rate_class": p["rate_class"],
        "is_master_bar": p["is_master_bar"],
        "min_los": p["min_los"],
        "max_los": p["max_los"],
        "base_rate": p["base_rate"],
        "floor_rate": p["floor_rate"],
        "ceiling_rate": p["ceiling_rate"],
        "status": p["status"],
        "published_rate": p["published_rate"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_inventory_day(inv):
    # Always recompute derived availability before emitting.
    recompute_availability(inv)
    return {
        "id": inv["id"],
        "room_type_id": inv["room_type_id"],
        "stay_date": inv["stay_date"],
        "physical_capacity": inv["physical_capacity"],
        "group_held_rooms": inv["group_held_rooms"],
        "transient_sold_rooms": inv["transient_sold_rooms"],
        "transient_revenue": inv["transient_revenue"],
        "rooms_sold": inv["rooms_sold"],
        "rooms_available": inv["rooms_available"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def ser_rate_decision(d):
    return {
        "id": d["id"],
        "rate_plan_id": d["rate_plan_id"],
        "stay_date": d["stay_date"],
        "status": d["status"],
        "requested_rate": d["requested_rate"],
        "yielded_rate": d["yielded_rate"],
        "applied_yield_rule_id": d["applied_yield_rule_id"],
        "last_room_premium_applied": d["last_room_premium_applied"],
        "reject_reason": d["reject_reason"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_yield_rule(y):
    return {
        "id": y["id"],
        "property_id": y["property_id"],
        "name": y["name"],
        "occupancy_threshold_pct": y["occupancy_threshold_pct"],
        "adjustment_pct": y["adjustment_pct"],
        "priority": y["priority"],
        "enabled": y["enabled"],
        "created_at": y["created_at"],
        "updated_at": y["updated_at"],
        "version": y["version"],
    }


def ser_group_block(g):
    return {
        "id": g["id"],
        "room_type_id": g["room_type_id"],
        "group_name": g["group_name"],
        "arrival_date": g["arrival_date_iso"],
        "nights": g["nights"],
        "rooms_per_night": g["rooms_per_night"],
        "offered_rate": g["offered_rate"],
        "status": g["status"],
        "displacement_cost": g["displacement_cost"],
        "recommendation": g["recommendation"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_channel_mapping(m):
    return {
        "id": m["id"],
        "rate_plan_id": m["rate_plan_id"],
        "channel": m["channel"],
        "markup_pct": m["markup_pct"],
        "manual_rate_override": m["manual_rate_override"],
        "parity_status": m["parity_status"],
        "channel_rate": m["channel_rate"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_competitor_rate(c):
    return {
        "id": c["id"],
        "property_id": c["property_id"],
        "competitor_name": c["competitor_name"],
        "stay_date": c["stay_date"],
        "shopped_rate": c["shopped_rate"],
        "shopped_at": c["shopped_at"],
        "created_at": c["created_at"],
    }


def ser_transient_reservation(t):
    return {
        "id": t["id"],
        "room_type_id": t["room_type_id"],
        "rate_plan_id": t["rate_plan_id"],
        "arrival_date": t["arrival_date_iso"],
        "nights": t["nights"],
        "rooms": t["rooms"],
        "status": t["status"],
        "booked_rate": t["booked_rate"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }
