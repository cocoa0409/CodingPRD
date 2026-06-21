"""Serialize internal entity dicts into API representations.

Strips internal-only keys (those starting with '_') and re-derives the
read-only computed fields that the PRD exposes on each resource.
"""
from db import store


def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Re-derivation of live computed fields (PRD §3.1, §3.3)
# ---------------------------------------------------------------------------
def zone_active_order_count(zone_id):
    """Count orders in the zone whose fulfillment_status is PLACED/ROUTED/PICKED_UP."""
    active = {"PLACED", "ROUTED", "PICKED_UP"}
    return sum(
        1
        for o in store.orders.values()
        if o["zone_id"] == zone_id and o["fulfillment_status"] in active
    )


def dasher_active_delivery_count(dasher_id):
    """Count the dasher's deliveries in OFFERED/ACCEPTED/EN_ROUTE."""
    active = {"OFFERED", "ACCEPTED", "EN_ROUTE"}
    return sum(
        1
        for d in store.deliveries.values()
        if d["dasher_id"] == dasher_id and d["fulfillment_status"] in active
    )


def dasher_lifetime_earnings(dasher_id):
    """Sum settled_pay_cents over the dasher's SETTLED earnings records."""
    return sum(
        e["settled_pay_cents"] or 0
        for e in store.earnings_records.values()
        if e["dasher_id"] == dasher_id and e["status"] == "SETTLED"
    )


# ---------------------------------------------------------------------------
# Per-entity serializers
# ---------------------------------------------------------------------------
def serialize_zone(z):
    out = _public(z)
    out["active_order_count"] = zone_active_order_count(z["id"])
    return out


def serialize_restaurant(r):
    return _public(r)


def serialize_menu_item(m):
    return _public(m)


def serialize_customer(c):
    return _public(c)


def serialize_dasher(d):
    out = _public(d)
    out["active_delivery_count"] = dasher_active_delivery_count(d["id"])
    out["lifetime_earnings_cents"] = dasher_lifetime_earnings(d["id"])
    return out


def serialize_order(o):
    return _public(o)


def serialize_line_item(li):
    return _public(li)


def serialize_delivery(d):
    return _public(d)


def serialize_tip_adjustment(t):
    return _public(t)


def serialize_order_issue(i):
    return _public(i)


def serialize_earnings_record(e):
    return _public(e)
