"""Order routes incl. pay/cancel/refund cascades (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE,
    ERR_FAN_FLAGGED,
    ERR_FAN_NOT_VERIFIED,
    ERR_QTY_MISMATCH,
    ERR_OFFER_EXPIRED,
    ERR_ALLOCATION_EXCEEDED,
    ERR_TICKET_ALREADY_SCANNED,
    ERR_STALE_VERSION,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, require_str, require_int, sorted_by_creation
from services import calculations
from services.cascades import event_sold_out_cascade

bp = Blueprint("orders", __name__)


@bp.post("/orders")
def create_order():
    require_auth(["Fan"])()
    body = get_json_body()
    queue_entry_id = require_str(body, "queue_entry_id")
    fan_id = require_str(body, "fan_id")
    tier_id = require_str(body, "tier_id")
    quantity = require_int(body, "quantity")

    # existence (left-to-right: tier, fan, queue entry per dependency order)
    fan = get_or_404(db.fans, fan_id, "Fan")
    tier = get_or_404(db.price_tiers, tier_id, "PriceTier")
    qe = get_or_404(db.queue_entries, queue_entry_id, "QueueEntry")

    # ownership: acting Fan owns the order (fan_id) and must equal the entry's fan
    if g.user_id != fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner")
    if qe.get("fan_id") != fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Queue entry belongs to another fan")

    # state: queue entry must be OFFERED to be redeemed
    if qe["status"] != "OFFERED":
        raise APIError(ERR_INVALID_STATE, 409, "Queue entry is not OFFERED")

    # priority 12: quantity must equal entry.requested_qty and lie in 1..6
    if quantity < 1 or quantity > calculations.MAX_PER_FAN:
        raise APIError(ERR_QTY_MISMATCH, 422, "quantity out of range")
    if quantity != qe["requested_qty"]:
        raise APIError(ERR_QTY_MISMATCH, 422, "quantity != requested_qty")

    event = db.events.get(qe["event_id"])

    # priority 14: offer expiry
    now = db.now_dt()
    exp = db.parse_iso_dt(qe.get("offer_expires_at"))
    if exp is not None and now > exp:
        raise APIError(ERR_OFFER_EXPIRED, 422, "Offer has expired")

    # priority 15: allocation cap — order may not push occupancy past allocation.
    # Seats are already reserved for this OFFERED entry; paying converts them.
    # Guard against quantity exceeding what the tier can hold.
    occupancy = tier["reserved_count"] + tier["sold_count"]
    if occupancy > tier["allocation"]:
        raise APIError(ERR_ALLOCATION_EXCEEDED, 422, "Allocation exceeded")

    is_presale = event is not None and event["sales_status"] == "PRESALE"
    unit_price = calculations.dynamic_unit_price(event, tier, is_presale)
    subtotal, service_fee, total = calculations.order_total(unit_price, quantity)

    order = db.stamp_common(
        {
            "queue_entry_id": queue_entry_id,
            "fan_id": fan_id,
            "tier_id": tier_id,
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "subtotal_cents": subtotal,
            "service_fee_cents": service_fee,
            "total_cents": total,
            "refund_amount_cents": 0,
            "status": "PENDING",
        }
    )
    db.orders[order["id"]] = order
    return ok_object(order, 201)


def _check_order_occ(order, body):
    expected = body.get("expected_order_version")
    if expected is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing expected_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_order_version must be an integer")
    if expected != order["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "Stale order version")


@bp.post("/orders/<oid>/pay")
def pay_order(oid):
    require_auth(["Fan"])()
    order = get_or_404(db.orders, oid, "Order")
    body = get_json_body()
    fan = db.fans.get(order["fan_id"])

    # ownership
    if g.user_id != order["fan_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner")

    # state gate (ERR_INVALID_STATE) applies to the TARGET resource, the Order:
    # the order must be PENDING for pay to be a defined transition.
    if order["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Order is not PENDING")
    qe = db.queue_entries.get(order["queue_entry_id"])
    now = db.now_dt()
    exp = db.parse_iso_dt(qe.get("offer_expires_at")) if qe is not None else None
    offer_lapsed = (qe is not None and qe["status"] == "EXPIRED") or (
        exp is not None and now > exp
    )
    # A linked queue entry that has lapsed (swept to EXPIRED, or whose
    # offer_expires_at has passed) is the offer-expiry business rule, surfaced
    # later in precedence as ERR_OFFER_EXPIRED. Only a linked entry that is
    # non-OFFERED for some other reason is a structural ERR_INVALID_STATE.
    if qe is None or (qe["status"] != "OFFERED" and not offer_lapsed):
        raise APIError(ERR_INVALID_STATE, 409, "Linked queue entry is not OFFERED")

    # priority 6: flag bar
    if fan is not None and fan["verification_status"] == "FLAGGED":
        raise APIError(ERR_FAN_FLAGGED, 403, "Fan is flagged")
    # priority 9: verified-fan restriction
    if fan is None or fan["verification_status"] != "VERIFIED":
        raise APIError(ERR_FAN_NOT_VERIFIED, 422, "Fan is not verified")

    # priority 14: offer expiry
    if offer_lapsed:
        raise APIError(ERR_OFFER_EXPIRED, 422, "Offer has expired")

    # priority 17: OCC
    _check_order_occ(order, body)

    quantity = order["quantity"]
    tier = db.price_tiers.get(order["tier_id"])
    event = db.events.get(qe["event_id"])

    # ---- commit (depth-3 cascade) ----
    order["status"] = "PAID"
    db.bump(order)

    qe["status"] = "PURCHASED"
    db.bump(qe)

    if tier is not None:
        tier["reserved_count"] -= quantity
        tier["sold_count"] += quantity
        db.bump(tier)

    # issue `quantity` tickets
    for i in range(quantity):
        ticket = db.stamp_common(
            {
                "order_id": order["id"],
                "event_id": event["id"] if event else qe["event_id"],
                "holder_fan_id": order["fan_id"],
                "seat_label": f"{tier['name'] if tier else 'GA'}-{tier['sold_count'] - quantity + i + 1 if tier else i + 1}",
                "entry_status": "VALID",
                "holding_status": "HELD",
            }
        )
        db.tickets[ticket["id"]] = ticket

    if event is not None:
        event["tickets_sold_count"] += quantity
        db.bump(event)

    if fan is not None:
        fan["completed_purchase_count"] += 1
        db.bump(fan)

    # cascade: sold-out
    if event is not None and event["tickets_sold_count"] == event["venue_capacity"]:
        if event["sales_status"] in ("PRESALE", "GENERAL"):
            event_sold_out_cascade(event)

    return ok_object(order, 200)


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    require_auth(["Fan"])()
    order = get_or_404(db.orders, oid, "Order")

    if g.user_id != order["fan_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner")
    if order["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Order is not PENDING")

    order["status"] = "CANCELLED"
    order["refund_amount_cents"] = 0
    db.bump(order)
    return ok_object(order, 200)


@bp.post("/orders/<oid>/refund")
def refund_order(oid):
    require_auth(["Fan"])()
    order = get_or_404(db.orders, oid, "Order")
    body = get_json_body()

    if g.user_id != order["fan_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner")
    if order["status"] != "PAID":
        raise APIError(ERR_INVALID_STATE, 409, "Order is not PAID")

    # priority 13: refund barred if any ticket SCANNED
    order_tickets = [t for t in db.tickets.values() if t.get("order_id") == oid]
    if any(t["entry_status"] == "SCANNED" for t in order_tickets):
        raise APIError(ERR_TICKET_ALREADY_SCANNED, 422, "A ticket is already scanned")

    # priority 17: OCC
    _check_order_occ(order, body)

    quantity = order["quantity"]
    fan = db.fans.get(order["fan_id"])
    tier = db.price_tiers.get(order["tier_id"])
    event = None
    if order_tickets:
        event = db.events.get(order_tickets[0].get("event_id"))
    if event is None:
        qe = db.queue_entries.get(order["queue_entry_id"])
        if qe is not None:
            event = db.events.get(qe.get("event_id"))

    refund = calculations.refund_amount(
        order["subtotal_cents"],
        fan["completed_purchase_count"] if fan else 0,
    )

    order["status"] = "REFUNDED"
    order["refund_amount_cents"] = refund
    db.bump(order)

    # VOID all tickets
    for t in order_tickets:
        if t["entry_status"] != "VOID":
            t["entry_status"] = "VOID"
            db.bump(t)

    if tier is not None:
        tier["sold_count"] -= quantity
        db.bump(tier)
    if event is not None:
        event["tickets_sold_count"] -= quantity
        db.bump(event)
    if fan is not None:
        fan["completed_purchase_count"] -= 1
        db.bump(fan)

    # cascade: re-open SOLD_OUT -> GENERAL
    if event is not None and event["sales_status"] == "SOLD_OUT":
        event["sales_status"] = "GENERAL"
        db.bump(event)

    return ok_object(order, 200)


@bp.get("/orders/<oid>")
def get_order(oid):
    require_auth(["Fan", "PromoterAdmin"])()
    order = get_or_404(db.orders, oid, "Order")
    return ok_object(order, 200)


@bp.get("/orders")
def list_orders():
    require_auth(["Fan", "PromoterAdmin"])()
    limit, offset = paginate_params(request.args)
    fan_id = request.args.get("fan_id")
    queue_entry_id = request.args.get("queue_entry_id")
    tier_id = request.args.get("tier_id")
    status = request.args.get("status")
    items = list(db.orders.values())
    if fan_id is not None:
        items = [o for o in items if o.get("fan_id") == fan_id]
    if queue_entry_id is not None:
        items = [o for o in items if o.get("queue_entry_id") == queue_entry_id]
    if tier_id is not None:
        items = [o for o in items if o.get("tier_id") == tier_id]
    if status is not None:
        items = [o for o in items if o.get("status") == status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
