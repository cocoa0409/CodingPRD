"""Order reservation/charge/cancel + payout creation (PRD §3.4, §3.5)."""
import db
import clock
import errors
from errors import err
from services import calc, recompute, seat_ops

RESERVATION_TTL_MINUTES = 30


def reservation_expiry():
    return clock.to_iso(clock.add_minutes(clock.now(), RESERVATION_TTL_MINUTES))


def create_payout_for_charge(order, listing):
    """Mint the ESCROWED payout for a charged order (calc seller_fee)."""
    seller = db.sellers.get(listing["seller_id"])
    trust_tier = seller["trust_tier"] if seller else "NEW"
    gross, rate, fee = calc.seller_fee(
        order["quantity"], order["locked_unit_price_cents"], trust_tier
    )
    net = gross - fee
    if net < 0:
        net = 0
    payout = {
        "order_id": order["id"],
        "seller_id": listing["seller_id"],
        "status": "ESCROWED",
        "gross_sale_cents": gross,
        "seller_fee_rate": rate,
        "seller_fee_cents": fee,
        "net_payout_cents": net,
        "clawback_cents": 0,
    }
    db.stamp_create(payout)
    db.payouts[payout["id"]] = payout
    if seller is not None:
        recompute.recompute_seller(seller)
    return payout


def redeem_credits_fifo(buyer, amount):
    """Consume `amount` cents of the buyer's ISSUED credits FIFO by created_at ASC,
    moving them ISSUED -> REDEEMED. (Whole-credit redemption.)"""
    if amount <= 0:
        return
    issued = [c for c in db.event_credits.values()
              if c["buyer_id"] == buyer["id"] and c["status"] == "ISSUED"]
    issued.sort(key=lambda c: (c["created_at"], c["id"]))
    remaining = amount
    for credit in issued:
        if remaining <= 0:
            break
        credit["status"] = "REDEEMED"
        db.touch(credit)
        remaining -= credit["amount_cents"]


def charge(order):
    """PENDING -> CHARGED."""
    if order["payment_status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Order is not PENDING")

    listing = db.listings.get(order["listing_id"])
    buyer = db.buyers.get(order["buyer_id"])

    # listing must be ACTIVE or SOLD_OUT (not DELISTED/FROZEN)
    if listing["status"] == "FROZEN":
        raise err(errors.ERR_LISTING_FROZEN, "Listing is frozen")
    if listing["status"] not in ("ACTIVE", "SOLD_OUT"):
        raise err(errors.ERR_INVALID_STATE, "Listing is not in a chargeable state")

    # temporal: must charge before reservation_expires_at
    if clock.now() >= clock.parse_iso(order["reservation_expires_at"]):
        raise err(errors.ERR_RESERVATION_EXPIRED, "Reservation has expired")

    # final buyer charge (variant=final): the applied credit is RECOMPUTED
    # (clamped) against the buyer's wallet AS OF charge time per PRD §3.4 — "the
    # applied credit is recomputed against the buyer's wallet_credit_cents as of
    # charge time. If the wallet shrank between reservation and charge, the final
    # total can exceed the estimate". A shrunken wallet therefore yields a higher
    # final, never a rejection.
    applied_elected = order.get("applied_credit_cents") or 0
    fee, total, applied = calc.buyer_charge(
        order["quantity"], order["locked_unit_price_cents"],
        applied_elected, buyer["wallet_credit_cents"]
    )
    order["buyer_fee_cents"] = fee
    order["final_total_cents"] = total

    # consume credits FIFO
    redeem_credits_fifo(buyer, applied)

    # held seats -> SOLD
    for seat in seat_ops.seats_for_order(order["id"]):
        if seat["status"] == "HELD":
            seat_ops.set_status(seat, "SOLD")

    order["payment_status"] = "CHARGED"
    order["_reached_charged"] = True
    recompute.recompute_order_lifecycle(order)
    db.touch(order)

    # payout ESCROWED
    create_payout_for_charge(order, listing)

    # recompute aggregates
    recompute.recompute_buyer(buyer)
    recompute.recompute_listing(listing)
    db.touch(listing)  # explicit Listing.version += 1 on charge per PRD §3.4
    return order


def cancel_reservation(order):
    """PENDING -> REFUNDED (manual). Seats return to AVAILABLE."""
    if order["payment_status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Order is not PENDING")
    _release_reservation(order)
    return order


def _release_reservation(order):
    """Shared logic for manual cancel and clock-sweep expiry of a PENDING order."""
    listing = db.listings.get(order["listing_id"])
    for seat in seat_ops.seats_for_order(order["id"]):
        if seat["status"] == "HELD":
            seat_ops.set_status(seat, "AVAILABLE", order_id=None)

    order["payment_status"] = "REFUNDED"
    recompute.recompute_order_lifecycle(order)
    db.touch(order)

    if listing is not None:
        recompute.recompute_listing(listing)
        db.touch(listing)  # Listing.version += 1 on release per PRD §3.4
