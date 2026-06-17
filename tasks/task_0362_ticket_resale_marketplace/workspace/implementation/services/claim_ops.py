"""GuaranteeClaim adjudication (PRD §3.7)."""
import db
import clock
import errors
from errors import err
from services import calc, recompute, seat_ops

OPEN_CLAIM_STATES = ("FILED", "INVESTIGATING", "REPLACEMENT_OFFERED")


def has_open_claim(order_id):
    for c in db.guarantee_claims.values():
        if c["order_id"] == order_id and c["status"] in OPEN_CLAIM_STATES:
            return True
    return False


def investigate(claim):
    if claim["status"] != "FILED":
        raise err(errors.ERR_INVALID_STATE, "Claim is not FILED")
    claim["status"] = "INVESTIGATING"
    db.touch(claim)


def offer_replacement(claim, offered_listing_id):
    if claim["status"] != "INVESTIGATING":
        raise err(errors.ERR_INVALID_STATE, "Claim is not INVESTIGATING")
    order = db.orders.get(claim["order_id"])
    offered = db.listings.get(offered_listing_id)
    # offered listing must be ACTIVE on the same event as the original order's listing
    orig_listing = db.listings.get(order["listing_id"])
    if offered["event_id"] != orig_listing["event_id"]:
        raise err(errors.ERR_REFERENTIAL_MISMATCH, "Offered listing not on same event")
    if offered["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Offered listing is not ACTIVE")
    if offered["available_seat_count"] < order["quantity"]:
        raise err(errors.ERR_INSUFFICIENT_SEATS, "Offered listing has insufficient seats")
    claim["status"] = "REPLACEMENT_OFFERED"
    claim["offered_listing_id"] = offered_listing_id
    db.touch(claim)


def reject_offer(claim):
    if claim["status"] != "REPLACEMENT_OFFERED":
        raise err(errors.ERR_INVALID_STATE, "Claim is not REPLACEMENT_OFFERED")
    claim["status"] = "INVESTIGATING"
    claim["round_number"] = claim["round_number"] + 1
    db.touch(claim)


def accept_offer(claim, expected_listing_version):
    if claim["status"] != "REPLACEMENT_OFFERED":
        raise err(errors.ERR_INVALID_STATE, "Claim is not REPLACEMENT_OFFERED")
    order = db.orders.get(claim["order_id"])
    offered = db.listings.get(claim["offered_listing_id"])

    # offered listing still ACTIVE with enough seats
    if offered["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Offered listing is no longer ACTIVE")
    if offered["available_seat_count"] < order["quantity"]:
        raise err(errors.ERR_INSUFFICIENT_SEATS, "Offered listing has insufficient seats")

    # OCC on offered listing (evaluated last)
    if expected_listing_version != offered["version"]:
        raise err(errors.ERR_STALE_LISTING_VERSION, "Offered listing version is stale")

    # mint replacement order on offered listing, locked_unit_price 0, CHARGED, seats SOLD
    replacement = {
        "listing_id": offered["id"],
        "buyer_id": order["buyer_id"],
        "quantity": order["quantity"],
        "payment_status": "CHARGED",
        "delivery_status": "AWAITING",
        "lifecycle_state": "OPEN",
        "locked_unit_price_cents": 0,
        "estimated_total_cents": 0,
        "final_total_cents": 0,
        "buyer_fee_cents": 0,
        "applied_credit_cents": 0,
        "reservation_expires_at": _reservation_expiry(),
        "replacement_of_order_id": order["id"],
        "_reached_charged": True,
    }
    db.stamp_create(replacement)
    db.orders[replacement["id"]] = replacement
    recompute.recompute_order_lifecycle(replacement)

    held = seat_ops.allocate_fifo(offered, order["quantity"], replacement["id"])
    for seat in held:
        seat_ops.set_status(seat, "SOLD")
    recompute.recompute_listing(offered)
    db.touch(offered)

    # replacement mints its own ESCROWED payout (gross 0 since locked price is 0)
    from services import order_ops
    order_ops.create_payout_for_charge(replacement, offered)

    # original order -> REPLACED; original SOLD/HELD seats -> VOID
    order["delivery_status"] = "REPLACED"
    for seat in seat_ops.seats_for_order(order["id"]):
        if seat["status"] in ("SOLD", "HELD"):
            seat_ops.set_status(seat, "VOID")
    recompute.recompute_order_lifecycle(order)
    db.touch(order)
    orig_listing = db.listings.get(order["listing_id"])
    if orig_listing is not None:
        recompute.recompute_listing(orig_listing)

    # original ESCROWED payout -> CANCELLED
    affected_sellers = set()
    for payout in db.payouts.values():
        if payout["order_id"] == order["id"] and payout["status"] == "ESCROWED":
            payout["net_payout_cents"] = 0
            payout["status"] = "CANCELLED"
            db.touch(payout)
            affected_sellers.add(payout["seller_id"])

    # claim resolves
    claim["status"] = "RESOLVED_REPLACED"
    claim["replacement_order_id"] = replacement["id"]
    db.touch(claim)

    # recompute affected sellers and buyer
    affected_sellers.add(offered["seller_id"])
    for sid in affected_sellers:
        s = db.sellers.get(sid)
        if s:
            recompute.recompute_seller(s)
    buyer = db.buyers.get(order["buyer_id"])
    if buyer:
        recompute.recompute_buyer(buyer)


def refund(claim):
    if claim["status"] not in ("INVESTIGATING", "REPLACEMENT_OFFERED"):
        raise err(errors.ERR_INVALID_STATE, "Claim cannot be refunded from %s" % claim["status"])
    order = db.orders.get(claim["order_id"])

    paid = order.get("final_total_cents") or 0
    reason = claim["reason"]
    refund_amount = paid  # both variants refund the cash paid
    claim["refund_amount_cents"] = refund_amount

    # order CHARGED -> REFUNDED
    if order["payment_status"] == "CHARGED":
        order["payment_status"] = "REFUNDED"
        recompute.recompute_order_lifecycle(order)
        db.touch(order)

    # ESCROWED/RELEASABLE payout -> CLAWED_BACK
    affected_sellers = set()
    for payout in db.payouts.values():
        if payout["order_id"] == order["id"] and payout["status"] in ("ESCROWED", "RELEASABLE"):
            payout["clawback_cents"] = payout["net_payout_cents"]
            payout["net_payout_cents"] = 0
            payout["status"] = "CLAWED_BACK"
            db.touch(payout)
            affected_sellers.add(payout["seller_id"])

    # SOLD seats -> VOID
    for seat in seat_ops.seats_for_order(order["id"]):
        if seat["status"] == "SOLD":
            seat_ops.set_status(seat, "VOID")
    listing = db.listings.get(order["listing_id"])
    if listing is not None:
        recompute.recompute_listing(listing)

    # protection-refund variant re-issues a fresh ISSUED credit for applied_credit_cents
    buyer = db.buyers.get(order["buyer_id"])
    applied = order.get("applied_credit_cents") or 0
    if reason in ("NOT_DELIVERED", "INVALID_BARCODE", "DUPLICATE_SEAT") and applied > 0:
        event_id = listing["event_id"] if listing else None
        credit = {
            "buyer_id": order["buyer_id"],
            "event_id": event_id,
            "source_order_id": order["id"],
            "amount_cents": applied,
            "status": "ISSUED",
            "bonus_applied": False,
        }
        db.stamp_create(credit)
        db.event_credits[credit["id"]] = credit

    claim["status"] = "RESOLVED_REFUNDED"
    db.touch(claim)

    for sid in affected_sellers:
        s = db.sellers.get(sid)
        if s:
            recompute.recompute_seller(s)
    if buyer:
        recompute.recompute_buyer(buyer)


def deny(claim):
    if claim["status"] not in ("FILED", "INVESTIGATING"):
        raise err(errors.ERR_INVALID_STATE, "Claim cannot be denied from %s" % claim["status"])
    claim["status"] = "DENIED"
    db.touch(claim)


def _reservation_expiry():
    return clock.to_iso(clock.add_minutes(clock.now(), 30))
