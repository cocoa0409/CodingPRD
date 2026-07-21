"""Shared write-path workflows: order construction, attendee minting,
order fulfilment re-derivation, and the two multi-hop cascades."""
import datetime

import db
from services import constants as C
from services import derive, refunds


# --------------------------------------------------------------------------
# order construction
# --------------------------------------------------------------------------
def create_order(event, buyer, lines, promo=None, discount=0):
    """Create an Order plus its OrderItems.

    `lines` is a list of dicts already priced by services.pricing, each holding
    ticket_type_id, seat_block_id, quantity, seat_numbers and the four money
    fields. Callers own all validation; this function performs no checks.
    """
    hold_expires_at = db.now() + datetime.timedelta(minutes=C.SEAT_HOLD_MINUTES)

    order = db.base_record()
    order.update(
        {
            "event_id": event["id"],
            "buyer_id": buyer["id"],
            "promo_code_id": promo["id"] if promo else None,
            "payment_status": "PENDING",
            "fulfillment_status": "HELD",
            "subtotal_cents": sum(l["line_face_cents"] for l in lines),
            "discount_cents": discount,
            "fee_total_cents": sum(l["line_fee_cents"] for l in lines),
            "buyer_total_cents": 0,
            "organizer_gross_cents": 0,
            "refunded_cents": 0,
            "hold_expires_at": db.iso(hold_expires_at),
            "paid_at": None,
        }
    )

    from services.pricing import totals

    order.update(
        totals(
            event["fee_mode"],
            order["subtotal_cents"],
            order["discount_cents"],
            order["fee_total_cents"],
        )
    )
    db.store.orders[order["id"]] = order

    for line in lines:
        item = db.base_record()
        item.update(
            {
                "order_id": order["id"],
                "ticket_type_id": line["ticket_type_id"],
                "seat_block_id": line.get("seat_block_id"),
                "quantity": line["quantity"],
                "seat_numbers": list(line.get("seat_numbers") or []),
                "unit_price_cents": line["unit_price_cents"],
                "per_ticket_fee_cents": line["per_ticket_fee_cents"],
                "line_face_cents": line["line_face_cents"],
                "line_fee_cents": line["line_fee_cents"],
            }
        )
        db.store.order_items[item["id"]] = item

    db.touch(event)
    return order


# --------------------------------------------------------------------------
# admissions
# --------------------------------------------------------------------------
def mint_attendees(order, event, buyer):
    minted = []
    for item in derive.order_items_of(order["id"]):
        if item["seat_numbers"]:
            seats = list(item["seat_numbers"])
        else:
            seats = [None] * item["quantity"]
        for seat_number in seats:
            attendee = db.base_record()
            attendee.update(
                {
                    "order_id": order["id"],
                    "order_item_id": item["id"],
                    "ticket_type_id": item["ticket_type_id"],
                    "event_id": event["id"],
                    "buyer_id": buyer["id"],
                    "seat_block_id": item["seat_block_id"] if seat_number is not None else None,
                    "seat_number": seat_number,
                    "holder_email": buyer["email"],
                    "status": "ISSUED",
                    "checked_in_at": None,
                }
            )
            db.store.attendees[attendee["id"]] = attendee
            minted.append(attendee)
    return minted


def rederive_order_fulfillment(order):
    """Re-derive the fulfilment dimension after a scan or an undo."""
    if order["fulfillment_status"] not in ("ISSUED", "CHECKED_IN_PARTIAL", "CHECKED_IN_FULL"):
        return
    attendees = [a for a in derive.attendees_of_order(order["id"]) if a["status"] != "VOIDED"]
    if not attendees:
        return
    checked_in = [a for a in attendees if a["status"] == "CHECKED_IN"]
    if not checked_in:
        target = "ISSUED"
    elif len(checked_in) == len(attendees):
        target = "CHECKED_IN_FULL"
    else:
        target = "CHECKED_IN_PARTIAL"
    if target != order["fulfillment_status"]:
        order["fulfillment_status"] = target
        db.touch(order)


# --------------------------------------------------------------------------
# refund settlement cascade (PRD §3.8, four hops)
# --------------------------------------------------------------------------
def settle_refund(refund_request):
    order = db.store.orders[refund_request["order_id"]]
    event = db.store.events[order["event_id"]]

    # HOP 1
    refund_request["status"] = "SETTLED"
    refund_request["settled_at"] = db.now_iso()
    db.touch(refund_request)

    # HOP 2
    previous_payment_status = order["payment_status"]
    order["refunded_cents"] += refund_request["refund_amount_cents"]
    if order["refunded_cents"] == order["buyer_total_cents"]:
        order["payment_status"] = "REFUNDED"
        if previous_payment_status == "PAID":
            order["fulfillment_status"] = "VOIDED"
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
    db.touch(order)

    for entry in refund_request["item_refunds"]:
        remaining = entry["quantity"]
        for attendee in derive.attendees_of_item(entry["order_item_id"]):
            if remaining <= 0:
                break
            if attendee["status"] in C.LIVE_ATTENDEE_STATUSES:
                attendee["status"] = "VOIDED"
                db.touch(attendee)
                remaining -= 1

    organizer = db.store.organizers.get(event["organizer_id"])
    if organizer is not None:
        organizer["lifetime_refunds_cents"] += refund_request["organizer_charged_cents"]
        db.touch(organizer)

    # HOP 3 + HOP 4
    from services.payouts import apply_chain

    for payout in db.store.payouts.values():
        if payout["event_id"] != event["id"] or payout["status"] not in ("ACCRUING", "ELIGIBLE"):
            continue
        apply_chain(payout, event)
        if payout["net_amount_cents"] < 0:
            payout["status"] = "ON_HOLD"
        db.touch(payout)

    return refund_request


# --------------------------------------------------------------------------
# event cancellation cascade (PRD §3.8, five hops)
# --------------------------------------------------------------------------
def cancel_event(event):
    was_draft = event["status"] == "DRAFT"

    # HOP 1
    event["status"] = "CANCELLED"
    db.touch(event)

    if not was_draft:
        refund_pending_orders = []

        # HOP 2
        for order in derive.orders_of_event(event["id"]):
            if order["fulfillment_status"] not in C.LIVE_ORDER_FULFILLMENTS:
                continue
            order["fulfillment_status"] = "VOIDED"
            if order["payment_status"] == "PAID":
                order["payment_status"] = "REFUND_PENDING"
                refund_pending_orders.append(order)
            db.touch(order)

            # HOP 3 + HOP 4 (seat/inventory release is derived from status)
            for attendee in derive.attendees_of_order(order["id"]):
                if attendee["status"] in ("ISSUED", "CHECKED_IN"):
                    attendee["status"] = "VOIDED"
                    db.touch(attendee)

        # HOP 5
        for order in refund_pending_orders:
            item_refunds = []
            for item in derive.order_items_of(order["id"]):
                remaining = item["quantity"] - derive.settled_refund_quantity(item["id"])
                if remaining > 0:
                    item_refunds.append(
                        {"order_item_id": item["id"], "quantity": remaining}
                    )
            record = db.base_record()
            record.update(
                {
                    "order_id": order["id"],
                    "policy": "FEE_INCLUDED",
                    "status": "APPROVED",
                    "item_refunds": item_refunds,
                    "reason": "Event cancelled",
                    "settled_at": None,
                }
            )
            record.update(
                refunds.compute(order, item_refunds, "FEE_INCLUDED", event["fee_mode"])
            )
            db.store.refund_requests[record["id"]] = record

    # waitlist expiry — runs for every cancellation, including from DRAFT
    tier_ids = {t["id"] for t in derive.ticket_types_of_event(event["id"])}
    for entry in db.store.waitlist_entries.values():
        if entry["ticket_type_id"] in tier_ids and entry["status"] in ("WAITING", "OFFERED"):
            entry["status"] = "EXPIRED"
            db.touch(entry)

    return event
