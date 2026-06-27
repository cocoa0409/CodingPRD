"""Serializers: convert stored records into API response dicts (public fields only).

Recompute-on-read fields (PRD §2.7, §3.1, §3.2, §3.4):
  - Sku.active_markdown_id / lifecycle : derived from clock + markdowns
  - Markdown.status                    : derived from clock
  - FishingLicense.status              : derived from clock; license has NO
                                         updated_at / version (PRD §2.4)
"""

from clock import clock
from db import db
from services import pricing


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def sku(rec):
    clock_dt = clock.now()
    m = pricing.active_markdown_for_sku(rec["id"], clock_dt)
    active_markdown_id = m["id"] if m else None
    if m is not None:
        lifecycle = m["markdown_kind"]  # SEASONAL or CLEARANCE
    else:
        lifecycle = rec.get("lifecycle_base", "STANDARD")
    out = _common(rec)
    out.update({
        "sport": rec["sport"],
        "name": rec["name"],
        "size_label": rec["size_label"],
        "is_footwear": rec["is_footwear"],
        "base_price_cents": rec["base_price_cents"],
        "requires_license_permit": rec["requires_license_permit"],
        "embroiderable": rec["embroiderable"],
        "lifecycle": lifecycle,
        "active_markdown_id": active_markdown_id,
    })
    return out


def store(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "state_code": rec["state_code"],
        "ship_from_store_enabled": rec["ship_from_store_enabled"],
        "pickup_enabled": rec["pickup_enabled"],
    })
    return out


def store_inventory(rec):
    out = _common(rec)
    out.update({
        "store_id": rec["store_id"],
        "sku_id": rec["sku_id"],
        "on_hand_qty": rec["on_hand_qty"],
        "reserved_qty": rec["reserved_qty"],
        "available_qty": rec["available_qty"],
    })
    return out


def customer(rec):
    out = _common(rec)
    out.update({
        "email": rec["email"],
        "full_name": rec["full_name"],
        "home_state_code": rec["home_state_code"],
        "loyalty_points": rec["loyalty_points"],
        "loyalty_tier": rec["loyalty_tier"],
    })
    return out


def order(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "store_id": rec["store_id"],
        "fulfillment_type": rec["fulfillment_type"],
        "payment_status": rec["payment_status"],
        "fulfillment_status": rec["fulfillment_status"],
        "provisional_total_cents": rec["provisional_total_cents"],
        "final_total_cents": rec["final_total_cents"],
        "loyalty_points_awarded": rec["loyalty_points_awarded"],
    })
    return out


def order_line(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "sku_id": rec["sku_id"],
        "store_inventory_id": rec["store_inventory_id"],
        "quantity": rec["quantity"],
        "unit_price_cents": rec["unit_price_cents"],
        "embroidery_text": rec["embroidery_text"],
        "line_status": rec["line_status"],
    })
    return out


def service_ticket(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "store_id": rec["store_id"],
        "service_type": rec["service_type"],
        "part_sku_id": rec["part_sku_id"],
        "part_store_inventory_id": rec["part_store_inventory_id"],
        "status": rec["status"],
        "service_fee_cents": rec["service_fee_cents"],
    })
    return out


def fishing_license(rec):
    clock_dt = clock.now()
    from clock import parse_iso8601
    valid_until = parse_iso8601(rec["valid_until"])
    status = "ACTIVE" if clock_dt < valid_until else "EXPIRED"
    # FishingLicense carries only id + created_at (PRD §2.4): no updated_at/version.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "customer_id": rec["customer_id"],
        "issuing_store_id": rec["issuing_store_id"],
        "residency": rec["residency"],
        "valid_from": rec["valid_from"],
        "valid_until": rec["valid_until"],
        "fee_cents": rec["fee_cents"],
        "status": status,
    }


def price_match_claim(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "order_line_id": rec["order_line_id"],
        "competitor_price_cents": rec["competitor_price_cents"],
        "status": rec["status"],
        "approved_unit_price_cents": rec["approved_unit_price_cents"],
    })
    return out


def markdown(rec):
    clock_dt = clock.now()
    status = pricing.markdown_status(rec, clock_dt)
    out = _common(rec)
    out.update({
        "sku_id": rec["sku_id"],
        "markdown_kind": rec["markdown_kind"],
        "percent_off": rec["percent_off"],
        "effective_from": rec["effective_from"],
        "effective_until": rec["effective_until"],
        "status": status,
    })
    return out


def team_order(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "store_id": rec["store_id"],
        "team_name": rec["team_name"],
        "status": rec["status"],
        "total_units": rec["total_units"],
        "spawned_order_id": rec["spawned_order_id"],
    })
    return out


def team_order_line(rec):
    out = _common(rec)
    out.update({
        "team_order_id": rec["team_order_id"],
        "sku_id": rec["sku_id"],
        "quantity": rec["quantity"],
        "embroidery_text": rec["embroidery_text"],
    })
    return out
