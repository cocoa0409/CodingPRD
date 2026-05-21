"""Order-side business logic: placement, accept, cancel, ready, etc."""
from __future__ import annotations

import datetime as _dt

from . import projections, resolvers
from .clock import clock, iso_format, iso_now
from .entities import bump, init_versioned
from .envelope import (
    err_forbidden,
    err_invalid_state,
    err_not_found,
    err_order_invalid,
    err_restaurant_unavailable,
    err_validation,
)
from .geo import haversine_km, round_km_1dp
from .peak import is_peak_time
from .pricing import (
    commission_flat_cents,
    commission_tiered_cents,
    delivery_fee_solo_cents,
)
from .store import store


MIN_SUBTOTAL_CENTS = 100
PROMISED_TIME_OFFSET_MIN = 45


def _draw_credit(customer: dict, gross_cents: int) -> int:
    """Spend down credit_balance_cents up to gross. Returns amount drawn."""
    available = customer.get("credit_balance_cents", 0)
    drawn = min(available, gross_cents)
    customer["credit_balance_cents"] = available - drawn
    return drawn


def _restore_credit(customer: dict, amount_cents: int) -> None:
    customer["credit_balance_cents"] = customer.get("credit_balance_cents", 0) + amount_cents


def place_order(
    customer_id, restaurant_id, items_payload, actor_user_id: str
) -> dict:
    """Validate and create a new Order. Raises APIErrors per PRD."""
    # Step 4 (FK existence): customer_id, restaurant_id, then each menu_item_id
    if not isinstance(customer_id, str) or customer_id not in store.customers:
        raise err_not_found(f"Customer '{customer_id}' not found")
    if not isinstance(restaurant_id, str) or restaurant_id not in store.restaurants:
        raise err_not_found(f"Restaurant '{restaurant_id}' not found")
    if not isinstance(items_payload, list):
        raise err_order_invalid("items must be a non-empty array")
    # Per PRD §2.6 priority: FK existence (#4) before shape (#11). Iterate to collect
    # FK-target menu items so we can FK-check each one before identity/domain checks.
    sanitized_items = []
    for entry in items_payload:
        if not isinstance(entry, dict):
            raise err_order_invalid("each item must be an object")
        mid = entry.get("menu_item_id")
        if not isinstance(mid, str) or mid not in store.menu_items:
            raise err_not_found(f"MenuItem '{mid}' not found")
        sanitized_items.append((entry, mid))

    # Step 5 (identity): caller must equal customer_id
    if actor_user_id != customer_id:
        raise err_forbidden("Customer identity mismatch")

    customer = store.customers[customer_id]
    restaurant = store.restaurants[restaurant_id]

    # Step 7 (domain): restaurant active + menu items listed + belong to this restaurant.
    # These fire before the shape check (#11) so items=[] on a suspended restaurant returns
    # ERR_RESTAURANT_UNAVAILABLE, not ERR_ORDER_INVALID.
    if restaurant["status"] != "ACTIVE":
        raise err_restaurant_unavailable("Restaurant is not ACTIVE")
    for _entry, mid in sanitized_items:
        mi = store.menu_items[mid]
        if not mi["is_listed"]:
            raise err_restaurant_unavailable(f"MenuItem '{mid}' is not listed")
        if mi["restaurant_id"] != restaurant_id:
            raise err_restaurant_unavailable(
                f"MenuItem '{mid}' does not belong to the target restaurant"
            )

    # Step 11 (shape): items non-empty, quantity >= 1, subtotal >= 100
    if len(items_payload) == 0:
        raise err_order_invalid("items must be non-empty")
    items_clean = []
    subtotal = 0
    for entry, mid in sanitized_items:
        mi = store.menu_items[mid]
        qty = entry.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise err_order_invalid("each item.quantity must be an integer >= 1")
        # name and unit_price_cents snapshotted from the menu item at placement
        name = mi["name"]
        unit_price = mi["price_cents"]
        # If client provided values, ensure they match the canonical snapshot, but the snapshot wins.
        items_clean.append(
            {
                "menu_item_id": mid,
                "name": name,
                "unit_price_cents": unit_price,
                "quantity": qty,
            }
        )
        subtotal += unit_price * qty
    if subtotal < MIN_SUBTOTAL_CENTS:
        raise err_order_invalid("subtotal_cents must be at least 100")

    now = clock.now()
    distance = round_km_1dp(
        haversine_km(restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"])
    )
    is_peak = is_peak_time(now)
    promised = now + _dt.timedelta(minutes=PROMISED_TIME_OFFSET_MIN)

    provisional_delivery_fee = delivery_fee_solo_cents(distance, is_peak)
    if restaurant.get("commission_rate_override") is not None:
        provisional_commission = commission_flat_cents(
            subtotal, float(restaurant["commission_rate_override"])
        )
    else:
        provisional_commission = commission_tiered_cents(subtotal)

    order = init_versioned("Order")
    # Payment authorization: draw credit first, then card auth covers remainder.
    gross_charge = subtotal + provisional_delivery_fee  # what customer pays
    credit_used = _draw_credit(customer, gross_charge)
    bump(customer)

    order.update(
        {
            "customer_id": customer_id,
            "restaurant_id": restaurant_id,
            "items": items_clean,
            "subtotal_cents": subtotal,
            "distance_km": distance,
            "is_peak": is_peak,
            "promised_delivery_time": iso_format(promised),
            "provisional_delivery_fee_cents": provisional_delivery_fee,
            "final_delivery_fee_cents": None,
            "provisional_commission_cents": provisional_commission,
            "final_commission_cents": None,
            "actual_delivery_time": None,
            "minutes_late": None,
            "status": "PLACED",
            "payment_status": "AUTHORIZED",
            "_credit_used_cents": credit_used,
            "_gross_charge_cents": gross_charge,
        }
    )
    store.orders[order["id"]] = order
    return order


def cancel_order(order: dict) -> None:
    """Cancel a PLACED order (customer/restaurant/CS-initiated)."""
    if order["status"] != "PLACED":
        raise err_invalid_state("Order is not in PLACED state")
    _do_cancel(order)


def cancel_order_due_to_suspend(order: dict) -> None:
    """Suspend cascade: cancel PLACED orders without state-precondition error."""
    if order["status"] != "PLACED":
        return
    _do_cancel(order)


def _do_cancel(order: dict) -> None:
    # Refund any credit_balance that was drawn
    credit_used = order.pop("_credit_used_cents", 0)
    if credit_used:
        customer = store.customers.get(order["customer_id"])
        if customer:
            _restore_credit(customer, credit_used)
            bump(customer)
    order["status"] = "CANCELLED"
    order["payment_status"] = "VOIDED"
    bump(order)


def restaurant_accept(order: dict) -> None:
    """Restaurant accepts a PLACED order; restaurant must be ACTIVE."""
    if order["status"] != "PLACED":
        raise err_invalid_state(f"Cannot accept order in state {order['status']}")
    restaurant = store.restaurants[order["restaurant_id"]]
    if restaurant["status"] != "ACTIVE":
        raise err_restaurant_unavailable("Restaurant is not ACTIVE")
    order["status"] = "RESTAURANT_ACCEPTED"
    bump(order)


def restaurant_start_preparing(order: dict) -> None:
    """Restaurant signals preparation; system opens a dispatch offer afterward (caller-side)."""
    if order["status"] != "RESTAURANT_ACCEPTED":
        raise err_invalid_state(
            f"Cannot start preparing order in state {order['status']}"
        )
    order["status"] = "PREPARING"
    bump(order)


def restaurant_ready(order: dict) -> None:
    """Restaurant marks ready; legal only if an assignment is ACCEPTED or PICKED_UP."""
    if order["status"] != "PREPARING":
        raise err_invalid_state(
            f"Cannot mark ready in order state {order['status']}"
        )
    # Find any assignment with status ACCEPTED or PICKED_UP for this order
    has_ok_assignment = any(
        a["order_id"] == order["id"] and a["status"] in ("ACCEPTED", "PICKED_UP")
        for a in store.assignments.values()
    )
    if not has_ok_assignment:
        raise err_invalid_state("No rider has accepted this order yet")
    order["status"] = "READY_FOR_PICKUP"
    bump(order)
