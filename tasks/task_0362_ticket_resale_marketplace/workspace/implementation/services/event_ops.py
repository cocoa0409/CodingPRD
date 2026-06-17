"""Event lifecycle transitions and the event-cancel/complete cascades (PRD §3.1, §3.9)."""
import db
import clock
import errors
from errors import err
from services import calc, recompute, seat_ops

SELLING_STATES = ("ON_SALE", "LAST_MINUTE")


def open_sales(event):
    if event["status"] not in ("SCHEDULED", "POSTPONED"):
        raise err(errors.ERR_INVALID_STATE, "Event cannot open sales from %s" % event["status"])
    event["status"] = "ON_SALE"
    db.touch(event)


def enter_last_minute(event):
    if event["status"] != "ON_SALE":
        raise err(errors.ERR_INVALID_STATE, "Event cannot enter last-minute from %s" % event["status"])
    threshold = clock.add_minutes(
        clock.parse_iso(event["doors_open_at"]), -event["last_minute_cutoff_minutes"]
    )
    if clock.now() < threshold:
        raise err(errors.ERR_INVALID_STATE, "Last-minute window has not been reached")
    event["status"] = "LAST_MINUTE"
    db.touch(event)


def complete(event):
    if event["status"] not in ("ON_SALE", "LAST_MINUTE"):
        raise err(errors.ERR_INVALID_STATE, "Event cannot complete from %s" % event["status"])
    doors = clock.parse_iso(event["doors_open_at"])
    if clock.now() < doors:
        raise err(errors.ERR_INVALID_STATE, "Doors have not opened yet")

    event["status"] = "COMPLETED"
    db.touch(event)

    # hop 1: open listings -> DELISTED (ACTIVE, SOLD_OUT, DRAFT)
    for listing in _listings_for_event(event["id"]):
        if listing["status"] in ("ACTIVE", "SOLD_OUT", "DRAFT"):
            _delist_listing(listing)

    # hop 2: ESCROWED payouts on this event's orders -> RELEASABLE
    for payout in _payouts_for_event(event["id"]):
        if payout["status"] == "ESCROWED":
            payout["status"] = "RELEASABLE"
            db.touch(payout)
            # escrow_balance only counts ESCROWED; recompute seller
            seller = db.sellers.get(payout["seller_id"])
            if seller is not None:
                recompute.recompute_seller(seller)

    recompute.recompute_event(event)


def cancel(event):
    if event["status"] not in ("SCHEDULED", "ON_SALE", "LAST_MINUTE"):
        raise err(errors.ERR_INVALID_STATE, "Event cannot cancel from %s" % event["status"])

    event["status"] = "CANCELLED"
    db.touch(event)

    affected_sellers = set()
    affected_buyers = set()

    # hop 1: listings ACTIVE/SOLD_OUT/DRAFT/FROZEN -> DELISTED
    for listing in _listings_for_event(event["id"]):
        if listing["status"] in ("ACTIVE", "SOLD_OUT", "DRAFT", "FROZEN"):
            _delist_listing(listing, void_available=False)

    # hops 2-4 over orders on this event whose payment_status == CHARGED
    for order in _orders_for_event(event["id"]):
        if order["payment_status"] != "CHARGED":
            continue
        buyer = db.buyers.get(order["buyer_id"])
        # hop2: issue EventCredit, order -> CREDITED
        lifetime = buyer["lifetime_orders_count"] if buyer else 0
        amount, bonus = calc.event_credit_amount(
            order.get("final_total_cents") or 0, "CANCELLED", lifetime
        )
        credit = {
            "buyer_id": order["buyer_id"],
            "event_id": event["id"],
            "source_order_id": order["id"],
            "amount_cents": amount,
            "status": "ISSUED",
            "bonus_applied": bonus,
        }
        db.stamp_create(credit)
        db.event_credits[credit["id"]] = credit

        order["payment_status"] = "CREDITED"
        recompute.recompute_order_lifecycle(order)
        db.touch(order)

        # hop3: ESCROWED payout -> CLAWED_BACK
        for payout in _payouts_for_order(order["id"]):
            if payout["status"] == "ESCROWED":
                payout["clawback_cents"] = payout["net_payout_cents"]
                payout["net_payout_cents"] = 0
                payout["status"] = "CLAWED_BACK"
                db.touch(payout)
                affected_sellers.add(payout["seller_id"])

        # hop4: void seats on the credited orders
        for seat in seat_ops.seats_for_order(order["id"]):
            if seat["status"] != "VOID":
                seat_ops.set_status(seat, "VOID")

        if buyer is not None:
            affected_buyers.add(buyer["id"])

    # reconcile affected aggregates
    for sid in affected_sellers:
        s = db.sellers.get(sid)
        if s:
            recompute.recompute_seller(s)
    for bid in affected_buyers:
        b = db.buyers.get(bid)
        if b:
            recompute.recompute_buyer(b)
    for listing in _listings_for_event(event["id"]):
        recompute.recompute_listing(listing)
    recompute.recompute_event(event)


def postpone(event):
    if event["status"] not in ("SCHEDULED", "ON_SALE"):
        raise err(errors.ERR_INVALID_STATE, "Event cannot postpone from %s" % event["status"])
    event["status"] = "POSTPONED"
    db.touch(event)


# --- helpers ---

def _listings_for_event(event_id):
    return [l for l in db.listings.values() if l["event_id"] == event_id]


def _orders_for_event(event_id):
    listing_ids = {l["id"] for l in db.listings.values() if l["event_id"] == event_id}
    return [o for o in db.orders.values() if o["listing_id"] in listing_ids]


def _payouts_for_order(order_id):
    return [p for p in db.payouts.values() if p["order_id"] == order_id]


def _payouts_for_event(event_id):
    order_ids = {o["id"] for o in _orders_for_event(event_id)}
    return [p for p in db.payouts.values() if p["order_id"] in order_ids]


def _delist_listing(listing, void_available=True):
    listing["status"] = "DELISTED"
    db.touch(listing)
    if void_available:
        for seat in seat_ops.seats_for_listing(listing["id"]):
            if seat["status"] == "AVAILABLE":
                seat_ops.set_status(seat, "VOID")
        recompute.recompute_listing(listing)
