"""Derived-field reconciliation (PRD §2.4, §2.5).

Recomputing a derived field on a resource is itself a mutation: it refreshes
updated_at and increments version on the resource that carries the field. These
helpers each recompute one resource's derived fields and, if anything changed,
call db.touch() to bump version/updated_at exactly once.
"""
import db
from services import calc


def _bump_if_changed(record, changed):
    if changed:
        db.touch(record)


def recompute_listing(listing):
    """Reconcile a listing's seat-pool derived counts, status, effective price."""
    seats = [s for s in db.seats.values() if s["listing_id"] == listing["id"]]
    total = sum(1 for s in seats if s["status"] != "VOID")
    available = sum(1 for s in seats if s["status"] == "AVAILABLE")
    held = sum(1 for s in seats if s["status"] == "HELD")

    changed = False
    if listing.get("total_seat_count") != total:
        listing["total_seat_count"] = total
        changed = True
    if listing.get("available_seat_count") != available:
        listing["available_seat_count"] = available
        changed = True
    if listing.get("held_seat_count") != held:
        listing["held_seat_count"] = held
        changed = True

    # Pool-occupancy status reconciliation (ACTIVE <-> SOLD_OUT only).
    status = listing["status"]
    if status == "ACTIVE" and available == 0:
        listing["status"] = "SOLD_OUT"
        changed = True
    elif status == "SOLD_OUT" and available >= 1:
        listing["status"] = "ACTIVE"
        changed = True

    # Refresh effective price (FIXED uses ask; DYNAMIC tracks scarcity).
    section = db.sections.get(listing["section_id"])
    event = db.events.get(listing["event_id"])
    if section is not None and event is not None:
        eff = calc.effective_listing_price(listing, section, event)
        if listing.get("effective_price_cents") != eff:
            listing["effective_price_cents"] = eff
            changed = True

    _bump_if_changed(listing, changed)
    return listing


def refresh_dynamic_price(listing):
    """On read of a DYNAMIC listing, refresh effective_price_cents (PRD §3.3).
    This is a read-time projection — it must not bump version. We compute and
    store without touch() so repeated reads are idempotent for non-DYNAMIC and
    reflect current scarcity for DYNAMIC."""
    section = db.sections.get(listing["section_id"])
    event = db.events.get(listing["event_id"])
    if section is None or event is None:
        return listing
    listing["effective_price_cents"] = calc.effective_listing_price(listing, section, event)
    return listing


def recompute_section(section):
    section["capacity"] = section["row_count"] * section["seats_per_row"]


def recompute_venue(venue):
    count = sum(1 for s in db.sections.values() if s["venue_id"] == venue["id"])
    if venue.get("total_section_count") != count:
        venue["total_section_count"] = count
        db.touch(venue)


def recompute_event(event):
    count = sum(
        1 for l in db.listings.values()
        if l["event_id"] == event["id"] and l["status"] in ("ACTIVE", "SOLD_OUT")
    )
    if event.get("active_listing_count") != count:
        event["active_listing_count"] = count
        db.touch(event)


def recompute_seller(seller):
    escrow = sum(
        p["net_payout_cents"] for p in db.payouts.values()
        if p["seller_id"] == seller["id"] and p["status"] == "ESCROWED"
    )
    paid = sum(
        p["net_payout_cents"] for p in db.payouts.values()
        if p["seller_id"] == seller["id"] and p["status"] == "PAID"
    )
    open_flags = _count_open_flags_for_seller(seller["id"])

    escrow = max(escrow, 0)
    paid = max(paid, 0)
    changed = False
    if seller.get("escrow_balance_cents") != escrow:
        seller["escrow_balance_cents"] = escrow
        changed = True
    if seller.get("paid_out_balance_cents") != paid:
        seller["paid_out_balance_cents"] = paid
        changed = True
    if seller.get("open_fraud_flag_count") != open_flags:
        seller["open_fraud_flag_count"] = open_flags
        changed = True
    _bump_if_changed(seller, changed)


def _count_open_flags_for_seller(seller_id):
    """Count OPEN/UNDER_REVIEW flags raised against this seller's listings and seats."""
    listing_ids = {l["id"] for l in db.listings.values() if l["seller_id"] == seller_id}
    seat_ids = {s["id"] for s in db.seats.values() if s["listing_id"] in listing_ids}
    count = 0
    for f in db.fraud_flags.values():
        if f["status"] not in ("OPEN", "UNDER_REVIEW"):
            continue
        if f["subject_type"] == "LISTING" and f.get("listing_id") in listing_ids:
            count += 1
        elif f["subject_type"] == "SEAT" and f.get("seat_id") in seat_ids:
            count += 1
    return count


def recompute_buyer(buyer):
    wallet = sum(
        c["amount_cents"] for c in db.event_credits.values()
        if c["buyer_id"] == buyer["id"] and c["status"] == "ISSUED"
    )
    lifetime = sum(
        1 for o in db.orders.values()
        if o["buyer_id"] == buyer["id"] and o.get("_reached_charged", False)
    )
    wallet = max(wallet, 0)
    changed = False
    if buyer.get("wallet_credit_cents") != wallet:
        buyer["wallet_credit_cents"] = wallet
        changed = True
    if buyer.get("lifetime_orders_count") != lifetime:
        buyer["lifetime_orders_count"] = lifetime
        changed = True
    _bump_if_changed(buyer, changed)


def recompute_order_lifecycle(order):
    state = calc.order_lifecycle_rollup(order["payment_status"], order["delivery_status"])
    if order.get("lifecycle_state") != state:
        order["lifecycle_state"] = state
        # lifecycle is recomputed as part of an order mutation already in progress;
        # callers bump order.version explicitly per the transition. We do not
        # double-bump here.
    order["lifecycle_state"] = state
