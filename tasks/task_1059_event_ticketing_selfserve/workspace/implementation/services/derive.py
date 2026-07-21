"""Derived quantities: inventory truth (PRD §2.9), seat occupancy, promo uses."""
import db
from services.constants import LIVE_ATTENDEE_STATUSES, LIVE_ORDER_FULFILLMENTS


def _hold_is_live(order):
    if order["fulfillment_status"] != "HELD":
        return False
    deadline = db.parse_iso(order["hold_expires_at"])
    return deadline is not None and db.now() < deadline


def live_held_orders():
    return [o for o in db.store.orders.values() if _hold_is_live(o)]


def tier_sold(ticket_type_id):
    return sum(
        1
        for a in db.store.attendees.values()
        if a["ticket_type_id"] == ticket_type_id and a["status"] in LIVE_ATTENDEE_STATUSES
    )


def tier_held(ticket_type_id, exclude_waitlist_entry_id=None, exclude_order_id=None):
    total = 0
    for order in live_held_orders():
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        for item in db.store.order_items.values():
            if item["order_id"] == order["id"] and item["ticket_type_id"] == ticket_type_id:
                total += item["quantity"]
    for entry in db.store.waitlist_entries.values():
        if entry["ticket_type_id"] != ticket_type_id or entry["status"] != "OFFERED":
            continue
        if exclude_waitlist_entry_id is not None and entry["id"] == exclude_waitlist_entry_id:
            continue
        deadline = db.parse_iso(entry["offer_expires_at"])
        if deadline is not None and db.now() < deadline:
            total += entry["requested_quantity"]
    return total


def tier_available(ticket_type, exclude_waitlist_entry_id=None, exclude_order_id=None):
    return (
        ticket_type["quantity_total"]
        - tier_sold(ticket_type["id"])
        - tier_held(
            ticket_type["id"],
            exclude_waitlist_entry_id=exclude_waitlist_entry_id,
            exclude_order_id=exclude_order_id,
        )
    )


def occupied_seats(seat_block_id, exclude_order_id=None):
    """Seat numbers currently occupied inside a seat block."""
    taken = set()
    for a in db.store.attendees.values():
        if a["seat_block_id"] == seat_block_id and a["status"] in LIVE_ATTENDEE_STATUSES:
            if a["seat_number"] is not None:
                taken.add(a["seat_number"])
    for order in live_held_orders():
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        for item in db.store.order_items.values():
            if item["order_id"] == order["id"] and item["seat_block_id"] == seat_block_id:
                for number in item["seat_numbers"]:
                    taken.add(number)
    return taken


def seats_taken(seat_block_id):
    return len(occupied_seats(seat_block_id))


def promo_uses(promo_code_id):
    return sum(
        1
        for o in db.store.orders.values()
        if o["promo_code_id"] == promo_code_id
        and o["fulfillment_status"] in LIVE_ORDER_FULFILLMENTS
    )


def order_items_of(order_id):
    return db.ordered(
        [i for i in db.store.order_items.values() if i["order_id"] == order_id]
    )


def attendees_of_order(order_id):
    return db.ordered([a for a in db.store.attendees.values() if a["order_id"] == order_id])


def attendees_of_item(order_item_id):
    return db.ordered(
        [a for a in db.store.attendees.values() if a["order_item_id"] == order_item_id]
    )


def orders_of_event(event_id):
    return db.ordered([o for o in db.store.orders.values() if o["event_id"] == event_id])


def ticket_types_of_event(event_id):
    return db.ordered(
        [t for t in db.store.ticket_types.values() if t["event_id"] == event_id]
    )


def refund_requests_of_event(event_id):
    result = []
    for rr in db.store.refund_requests.values():
        order = db.store.orders.get(rr["order_id"])
        if order is not None and order["event_id"] == event_id:
            result.append(rr)
    return db.ordered(result)


def buyer_live_ticket_count(buyer_id, event_id):
    """Sum of order-line quantities across the buyer's live orders on the event."""
    total = 0
    for order in db.store.orders.values():
        if order["buyer_id"] != buyer_id or order["event_id"] != event_id:
            continue
        if order["fulfillment_status"] not in LIVE_ORDER_FULFILLMENTS:
            continue
        for item in db.store.order_items.values():
            if item["order_id"] == order["id"]:
                total += item["quantity"]
    return total


def settled_refund_quantity(order_item_id):
    """Quantity on a line already covered by SETTLED refund requests."""
    total = 0
    for rr in db.store.refund_requests.values():
        if rr["status"] != "SETTLED":
            continue
        for entry in rr["item_refunds"]:
            if entry.get("order_item_id") == order_item_id:
                total += entry.get("quantity", 0)
    return total


# --------------------------------------------------------------------------
# Event roll-ups — recomputed at the points the PRD declares.
# --------------------------------------------------------------------------
def event_gross_cents(event_id):
    return sum(
        o["organizer_gross_cents"]
        for o in db.store.orders.values()
        if o["event_id"] == event_id
        and o["payment_status"] in ("PAID", "REFUND_PENDING", "PARTIALLY_REFUNDED", "REFUNDED")
    )


def event_refunds_cents(event_id):
    total = 0
    for rr in refund_requests_of_event(event_id):
        if rr["status"] == "SETTLED":
            total += rr["organizer_charged_cents"]
    return total


def event_issued_count(event_id):
    return sum(
        1
        for a in db.store.attendees.values()
        if a["event_id"] == event_id and a["status"] in LIVE_ATTENDEE_STATUSES
    )


def event_checked_in_count(event_id):
    return sum(
        1
        for a in db.store.attendees.values()
        if a["event_id"] == event_id and a["status"] == "CHECKED_IN"
    )


def recompute_event_gross(event):
    event["gross_cents"] = event_gross_cents(event["id"])


def recompute_event_issued(event):
    event["issued_count"] = event_issued_count(event["id"])


def recompute_event_checked_in(event):
    event["checked_in_count"] = event_checked_in_count(event["id"])


def recompute_event_all(event):
    event["gross_cents"] = event_gross_cents(event["id"])
    event["refunds_cents"] = event_refunds_cents(event["id"])
    event["issued_count"] = event_issued_count(event["id"])
    event["checked_in_count"] = event_checked_in_count(event["id"])
