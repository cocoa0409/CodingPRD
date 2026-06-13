"""Calculation rules (SCAFFOLD §1.3 / PRD §3.5–§3.12).

Every monetary amount is integer cents; fractional cents are resolved with
round_half_up (PRD §2.8).
"""
from common import round_half_up
from db import store
from serializers import zone_active_order_count

ETA_MINUTES_PER_KM = 3
BPS_DENOMINATOR = 10000


# ---------------------------------------------------------------------------
# order_subtotal (PRD §3.4)
# ---------------------------------------------------------------------------
def line_extended_price(unit_price_cents, quantity):
    return unit_price_cents * quantity


def order_subtotal_cents(order):
    """Sum of extended_price_cents over the order's ORDERED lines."""
    total = 0
    for li in _order_lines(order["id"]):
        if li["status"] == "ORDERED":
            total += li["extended_price_cents"]
    return total


# ---------------------------------------------------------------------------
# order_service_fee (PRD §3.4 / §2.8): round PER LINE, then sum.
# ---------------------------------------------------------------------------
def line_service_fee(extended_price_cents, service_fee_bps):
    return round_half_up(extended_price_cents * service_fee_bps / BPS_DENOMINATOR)


def order_service_fee_cents(order, zone):
    total = 0
    for li in _order_lines(order["id"]):
        if li["status"] == "ORDERED":
            total += li["service_fee_cents"]
    return total


# ---------------------------------------------------------------------------
# Surge tier selection
# ---------------------------------------------------------------------------
def select_surge_multiplier(zone, demand):
    if demand >= zone["surge_tier_2_demand"]:
        return zone["surge_multiplier_tier_2"]
    if demand >= zone["surge_tier_1_demand"]:
        return zone["surge_multiplier_tier_1"]
    return zone["surge_multiplier_tier_0"]


# ---------------------------------------------------------------------------
# delivery_fee_quote (forward-looking; demand INCLUDES this order) (PRD §3.5)
# ---------------------------------------------------------------------------
def delivery_fee_quote(order, zone, restaurant):
    # active_order_count already includes this order (PLACED) at quote time.
    demand = zone_active_order_count(zone["id"])
    m = select_surge_multiplier(zone, demand)
    raw_distance_fee = zone["base_delivery_fee_cents"] + zone["per_km_fee_cents"] * restaurant["route_distance_km"]
    surged = round_half_up(raw_distance_fee * m)
    capped = min(surged, zone["delivery_fee_cap_cents"])
    subtotal = order["order_subtotal_cents"]
    small_order = zone["small_order_fee_cents"] if subtotal < zone["small_order_threshold_cents"] else 0
    return capped + small_order, m


# ---------------------------------------------------------------------------
# delivery_fee_final (settled; demand EXCLUDES this order) (PRD §3.9)
# ---------------------------------------------------------------------------
def delivery_fee_final(order, zone, delivery):
    demand = zone_active_order_count(zone["id"]) - 1
    m = select_surge_multiplier(zone, demand)
    raw_distance_fee = zone["base_delivery_fee_cents"] + zone["per_km_fee_cents"] * delivery["route_distance_km"]
    surged = round_half_up(raw_distance_fee * m)
    capped = min(surged, zone["delivery_fee_cap_cents"])
    subtotal = order["order_subtotal_cents"]
    small_order = zone["small_order_fee_cents"] if subtotal < zone["small_order_threshold_cents"] else 0
    return capped + small_order


# ---------------------------------------------------------------------------
# dasher pay: base, then tip, then guarantee top-up (pinned order) (PRD §3.9)
# ---------------------------------------------------------------------------
def dasher_pay_components(zone, route_distance_km, tip_cents):
    base_component = zone["dasher_base_pay_cents"] + zone["dasher_per_km_pay_cents"] * route_distance_km
    tip_component = tip_cents
    pre_guarantee = base_component + tip_component
    guarantee_topup = max(0, zone["dasher_min_guarantee_cents"] - pre_guarantee)
    settled = pre_guarantee + guarantee_topup
    return {
        "base_component_cents": base_component,
        "tip_component_cents": tip_component,
        "guarantee_topup_cents": guarantee_topup,
        "total_cents": settled,
    }


def dasher_pay_quote(zone, route_distance_km, tip_cents):
    return dasher_pay_components(zone, route_distance_km, tip_cents)["total_cents"]


# ---------------------------------------------------------------------------
# missing_item_refund (PRD §3.12)
# ---------------------------------------------------------------------------
def missing_item_refund(order, line, missing_quantity):
    per_unit = line["unit_price_cents"]
    raw = per_unit * missing_quantity
    headroom = order["order_subtotal_cents"] - order["refunded_cents"]
    return min(raw, headroom)


# ---------------------------------------------------------------------------
# eta_minutes (PRD §3.5)
# ---------------------------------------------------------------------------
def eta_minutes(restaurant):
    return restaurant["prep_minutes"] + restaurant["route_distance_km"] * ETA_MINUTES_PER_KM


# ---------------------------------------------------------------------------
# dispatch_selector (PRD §3.7)
# ---------------------------------------------------------------------------
def select_dasher(order):
    """Return the chosen dasher dict or None if the eligible pool is empty.

    Eligible: availability == ONLINE, home_zone_id == order.zone_id,
    active_delivery_count < max_batch_size. Sort key:
      1. active_delivery_count ASC, 2. max_batch_size DESC, 3. created_at ASC
    The dasher id is never a tie-break; _seq stands in for created_at to give a
    stable earliest-registered tie-break.
    """
    from serializers import dasher_active_delivery_count

    candidates = []
    for d in store.dashers.values():
        if d["availability"] != "ONLINE":
            continue
        if d["home_zone_id"] != order["zone_id"]:
            continue
        adc = dasher_active_delivery_count(d["id"])
        if adc < d["max_batch_size"]:
            candidates.append((adc, d))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (pair[0], -pair[1]["max_batch_size"], pair[1]["_seq"]))
    return candidates[0][1]


# ---------------------------------------------------------------------------
# prep_slot_overlap_check (PRD §3.6): half-open intervals
# ---------------------------------------------------------------------------
def prep_overlap_count(restaurant, new_start, new_end):
    """Count SCHEDULED orders on the same restaurant whose prep window overlaps.

    Windows [a,b) and [c,d) overlap iff a < d and c < b (touching = no overlap).
    """
    prep = restaurant["prep_minutes"]
    overlap = 0
    for o in store.orders.values():
        if o["restaurant_id"] != restaurant["id"]:
            continue
        if o["fulfillment_status"] != "SCHEDULED":
            continue
        if o.get("_scheduled_for_dt") is None:
            continue
        o_start = o["_scheduled_for_dt"]
        o_end = o_start + _minutes(prep)
        if new_start < o_end and o_start < new_end:
            overlap += 1
    return overlap


def _minutes(n):
    import datetime
    return datetime.timedelta(minutes=n)


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------
def _order_lines(order_id):
    return [li for li in store.line_items.values() if li["order_id"] == order_id]
