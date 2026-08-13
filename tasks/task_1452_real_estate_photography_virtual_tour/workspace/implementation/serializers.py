"""Serialize internal entities to their public JSON shape."""

from timeutil import dt_to_iso


def market_json(m):
    return {
        "id": m["id"],
        "market_code": m["market_code"],
        "display_name": m["display_name"],
        "pricing_multiplier_bps": m["pricing_multiplier_bps"],
        "standard_turnaround_hours": m["standard_turnaround_hours"],
        "twilight_slot_minutes": m["twilight_slot_minutes"],
        "travel_buffer_minutes": m["travel_buffer_minutes"],
        "weather_reschedule_credit_bps": m["weather_reschedule_credit_bps"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def photographer_json(p):
    return {
        "id": p["id"],
        "market_id": p["market_id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "equipment_packages": list(p["equipment_packages"]),
        "drone_certified": p["drone_certified"],
        "max_shoot_minutes_per_day": p["max_shoot_minutes_per_day"],
        "committed_minutes_by_day": dict(p["committed_minutes_by_day"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def client_agent_json(a):
    return {
        "id": a["id"],
        "brokerage_name": a["brokerage_name"],
        "full_name": a["full_name"],
        "email": a["email"],
        "home_market_id": a["home_market_id"],
        "credit_balance_cents": a["credit_balance_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def booking_json(b):
    return {
        "id": b["id"],
        "order_ref": b["order_ref"],
        "client_agent_id": b["client_agent_id"],
        "market_id": b["market_id"],
        "property_address": b["property_address"],
        "equipment_package": b["equipment_package"],
        "photo_count": b["photo_count"],
        "wants_virtual_tour": b["wants_virtual_tour"],
        "tour_variant": b["tour_variant"],
        "license_tier": b["license_tier"],
        "scheduled_start_utc": dt_to_iso(b["scheduled_start_utc"]),
        "scheduled_end_utc": dt_to_iso(b["scheduled_end_utc"]),
        "shoot_duration_minutes": b["shoot_duration_minutes"],
        "is_twilight": b["is_twilight"],
        "state": b["state"],
        "assigned_photographer_id": b["assigned_photographer_id"],
        "provisional_quote_cents": b["provisional_quote_cents"],
        "final_invoice_cents": b["final_invoice_cents"],
        "weather_credit_cents": b["weather_credit_cents"],
        "reschedule_count": b["reschedule_count"],
        "delivery_due_utc": dt_to_iso(b["delivery_due_utc"]),
        "delivered_at_utc": dt_to_iso(b["delivered_at_utc"]),
        "revision_window_closes_utc": dt_to_iso(b["revision_window_closes_utc"]),
        "revisions_used": b["revisions_used"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def checklist_item_json(it):
    return {
        "id": it["id"],
        "booking_id": it["booking_id"],
        "item_key": it["item_key"],
        "required": it["required"],
        "checked": it["checked"],
        "checked_at_utc": dt_to_iso(it["checked_at_utc"]),
        "created_at": it["created_at"],
        "updated_at": it["updated_at"],
        "version": it["version"],
    }


def addon_json(a):
    return {
        "id": a["id"],
        "booking_id": a["booking_id"],
        "kind": a["kind"],
        "state": a["state"],
        "price_cents": a["price_cents"],
        "extra_minutes": a["extra_minutes"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def authorization_json(a):
    return {
        "id": a["id"],
        "booking_id": a["booking_id"],
        "addon_id": a["addon_id"],
        "window_start_utc": dt_to_iso(a["window_start_utc"]),
        "window_end_utc": dt_to_iso(a["window_end_utc"]),
        "state": a["state"],
        "attempt_number": a["attempt_number"],
        "decided_at_utc": dt_to_iso(a["decided_at_utc"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def bundle_json(b):
    return {
        "id": b["id"],
        "booking_id": b["booking_id"],
        "state": b["state"],
        "photo_asset_count": b["photo_asset_count"],
        "tour_asset_url": b["tour_asset_url"],
        "delivered_at_utc": dt_to_iso(b["delivered_at_utc"]),
        "round_number": b["round_number"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def revision_json(r):
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "bundle_id": r["bundle_id"],
        "notes": r["notes"],
        "state": r["state"],
        "is_free": r["is_free"],
        "fee_cents": r["fee_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def tour_json(t):
    return {
        "id": t["id"],
        "booking_id": t["booking_id"],
        "variant": t["variant"],
        "state": t["state"],
        "hosted_url": t["hosted_url"],
        "published_at_utc": dt_to_iso(t["published_at_utc"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def license_json(g):
    return {
        "id": g["id"],
        "booking_id": g["booking_id"],
        "tier": g["tier"],
        "state": g["state"],
        "activated_at_utc": dt_to_iso(g["activated_at_utc"]),
        "fee_cents": g["fee_cents"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def reschedule_event_json(e):
    return {
        "id": e["id"],
        "booking_id": e["booking_id"],
        "kind": e["kind"],
        "old_start_utc": dt_to_iso(e["old_start_utc"]),
        "new_start_utc": dt_to_iso(e["new_start_utc"]),
        "reason_code": e["reason_code"],
        "credit_applied_cents": e["credit_applied_cents"],
        "created_at": e["created_at"],
    }
