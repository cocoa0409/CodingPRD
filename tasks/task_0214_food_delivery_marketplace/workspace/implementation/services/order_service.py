"""Order pricing recomputation and order-level state transitions."""
import errors
from common import init_common, touch, iso_now
from db import store
from services import calculations as calc


def recompute_order_pricing(order, zone, restaurant):
    """Recompute subtotal, per-line service fees, order service fee,
    delivery fee quote, surge multiplier, and ETA.

    Used at placement, line-item add, and scheduled-order release. The
    delivery-fee quote is forward-looking and reads the live zone demand,
    which only counts this order while it is PLACED.
    """
    # Per-line: extended price and service fee (round per line).
    for li in _order_lines(order["id"]):
        if li["status"] == "ORDERED":
            li["extended_price_cents"] = calc.line_extended_price(
                li["unit_price_cents"], li["quantity"]
            )
            li["service_fee_cents"] = calc.line_service_fee(
                li["extended_price_cents"], zone["service_fee_bps"]
            )

    order["order_subtotal_cents"] = calc.order_subtotal_cents(order)
    order["service_fee_cents"] = calc.order_service_fee_cents(order, zone)
    quote, multiplier = calc.delivery_fee_quote(order, zone, restaurant)
    order["delivery_fee_quote_cents"] = quote
    order["surge_multiplier_applied"] = multiplier
    order["eta_minutes"] = calc.eta_minutes(restaurant)


def _order_lines(order_id):
    return [li for li in store.line_items.values() if li["order_id"] == order_id]


# ---------------------------------------------------------------------------
# Release a scheduled order (SCHEDULED -> PLACED) (PRD §3.6)
# ---------------------------------------------------------------------------
def release_order(order):
    if order["fulfillment_status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_ORDER_STATE)
    if store.now() < order["_scheduled_for_dt"]:
        raise errors.err(errors.ERR_SCHEDULE_NOT_DUE)
    # Transition first so the order is counted in live zone demand when the
    # forward-looking quote re-reads active_order_count.
    order["fulfillment_status"] = "PLACED"
    zone = store.zones[order["zone_id"]]
    restaurant = store.restaurants[order["restaurant_id"]]
    recompute_order_pricing(order, zone, restaurant)
    touch(order)


# ---------------------------------------------------------------------------
# Dispatch (PLACED -> ROUTED), select dasher, create Delivery + EarningsRecord
# (PRD §3.7)
# ---------------------------------------------------------------------------
def dispatch_order(order):
    zone = store.zones[order["zone_id"]]
    restaurant = store.restaurants[order["restaurant_id"]]
    dasher = calc.select_dasher(order)
    if dasher is None:
        raise errors.err(errors.ERR_NO_DASHER_AVAILABLE)

    route_distance_km = restaurant["route_distance_km"]
    pay_quote = calc.dasher_pay_quote(zone, route_distance_km, order["tip_cents"])

    delivery = init_common(versioned=True)
    delivery.update({
        "order_id": order["id"],
        "dasher_id": dasher["id"],
        "route_distance_km": route_distance_km,
        "pay_quote_cents": pay_quote,
        "settled_pay_cents": None,
        "offered_at": iso_now(),
        "fulfillment_status": "OFFERED",
    })
    store.deliveries[delivery["id"]] = delivery

    earnings = init_common(versioned=True)
    earnings.update({
        "dasher_id": dasher["id"],
        "delivery_id": delivery["id"],
        "base_component_cents": None,
        "tip_component_cents": None,
        "guarantee_topup_cents": None,
        "settled_pay_cents": None,
        "status": "ACCRUED",
    })
    store.earnings_records[earnings["id"]] = earnings

    order["fulfillment_status"] = "ROUTED"
    touch(order)
    return delivery


# ---------------------------------------------------------------------------
# Cancel (SCHEDULED/PLACED/ROUTED -> CANCELLED), cascade + full refund
# (PRD §3.11)
# ---------------------------------------------------------------------------
def cancel_order(order):
    if order["fulfillment_status"] not in ("SCHEDULED", "PLACED", "ROUTED"):
        raise errors.err(errors.ERR_ORDER_NOT_CANCELLABLE)

    # Cancel a non-terminal Delivery (OFFERED or ACCEPTED) and reverse earnings.
    for d in store.deliveries.values():
        if d["order_id"] != order["id"]:
            continue
        if d["fulfillment_status"] in ("OFFERED", "ACCEPTED"):
            d["fulfillment_status"] = "CANCELLED"
            touch(d)
            for e in store.earnings_records.values():
                if e["delivery_id"] == d["id"] and e["status"] == "ACCRUED":
                    e["status"] = "REVERSED"
                    touch(e)

    order["fulfillment_status"] = "CANCELLED"
    order["billing_status"] = "REFUNDED"
    refund = (
        order["order_subtotal_cents"]
        + order["service_fee_cents"]
        + order["delivery_fee_quote_cents"]
        + order["tip_cents"]
    )
    order["refunded_cents"] = refund
    touch(order)
