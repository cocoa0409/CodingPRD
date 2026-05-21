"""Order placement and helpers."""

from datetime import timedelta

import compute
import state


def now_plus_minutes(mins):
    return state.now() + timedelta(minutes=mins)


def new_order(customer, restaurant, item_dicts):
    """Build the order record from validated inputs and snapshots.

    item_dicts is a list of {menu_item_id, name, unit_price_cents, quantity}.
    """
    now = state.now()
    oid = state.gen_id()
    subtotal = sum(i["unit_price_cents"] * i["quantity"] for i in item_dicts)
    distance_km = compute.distance_km_rounded(
        restaurant["lat"], restaurant["lng"],
        customer["lat"], customer["lng"],
    )
    peak = compute.is_peak_at(now)
    promised = now + timedelta(minutes=45)

    provisional_fee = compute.solo_delivery_fee_cents(distance_km, peak)
    provisional_comm = compute.commission_cents(
        subtotal, restaurant["commission_rate_override"]
    )

    rec = {
        "id": oid,
        "customer_id": customer["id"],
        "restaurant_id": restaurant["id"],
        "items": item_dicts,
        "subtotal_cents": subtotal,
        "distance_km": distance_km,
        "is_peak": peak,
        "promised_delivery_time": promised,
        "provisional_delivery_fee_cents": provisional_fee,
        "provisional_commission_cents": provisional_comm,
        "final_delivery_fee_cents": None,
        "final_commission_cents": None,
        "actual_delivery_time": None,
        "minutes_late": None,
        "status": "PLACED",
        "payment_status": "AUTHORIZED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    state.STORE.orders[oid] = rec
    return rec


def bump(order):
    order["updated_at"] = state.now()
    order["version"] = order["version"] + 1


def order_total_to_pay(order):
    """Customer-side total = subtotal + final or provisional delivery fee."""
    fee = order["final_delivery_fee_cents"]
    if fee is None:
        fee = order["provisional_delivery_fee_cents"]
    return order["subtotal_cents"] + fee
