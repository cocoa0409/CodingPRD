"""The box office: sales, comps, credit and refunds (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import serialize
from auth import (ROLE_ANON, ROLE_BOX, ROLE_EXEC, ROLE_MEMBER, authorize,
                  require_own_member)
from calc import MAX_TICKETS_PER_ORDER, price_order, refresh_member
from cascade import Ledger, refresh_showtime_rollup
from errors import ApiError
from response import object_response, paged
from store import new_record, now, ordered, touch
from validate import (REFUND_DESTINATIONS, bad, body, find, insert, must_find, opt_bool,
                      opt_id, opt_int, query_str, req_enum, req_id, req_int, req_str,
                      rows)

bp = Blueprint("orders", __name__)

ORDER_READ = (ROLE_BOX, ROLE_EXEC, ROLE_MEMBER)


def require_order_state(order, allowed):
    if order["status"] not in allowed:
        raise ApiError("ERR_TICKET_ORDER_INVALID_STATE",
                       "An order in %s does not admit this transition." % order["status"])


@bp.post("/ticket-orders")
def create_order():
    role, uid = authorize((ROLE_BOX, ROLE_MEMBER, ROLE_ANON))
    payload = body()
    member_id = opt_id(payload, "member_id")
    if role == ROLE_MEMBER:
        require_own_member(role, uid, member_id)
    elif role == ROLE_ANON and member_id is not None:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "An anonymous walk-up order cannot carry a member_id.")
    quantity = req_int(payload, "quantity", minimum=1, maximum=MAX_TICKETS_PER_ORDER)
    purchaser_email = req_str(payload, "purchaser_email")
    comp_quantity = opt_int(payload, "comp_quantity", 0, minimum=0)
    apply_credit = opt_bool(payload, "apply_credit", False)
    showtime_id = req_id(payload, "showtime_id")
    showtime = must_find("showtimes", showtime_id)
    member = must_find("members", member_id) if member_id is not None else None
    if showtime["status"] != "SCHEDULED":
        raise ApiError("ERR_SHOWTIME_INVALID_STATE",
                       "A screening in %s cannot be sold." % showtime["status"])
    if member is not None:
        refresh_member(member)
    # Ladder 18: advance access before public sales open.
    if showtime["public_sale_opens_at"] > now():
        hours = member["advance_access_hours"] if member is not None else 0
        window_opens = showtime["public_sale_opens_at"] - timedelta(hours=hours)
        if now() < window_opens:
            raise ApiError("ERR_ADVANCE_ACCESS_NOT_OPEN",
                           "This buyer's advance access window has not opened.")
    # Ladder 19: seats.
    if quantity > showtime["seats_available"]:
        raise ApiError("ERR_INSUFFICIENT_SEATS",
                       "Only %d seats remain." % showtime["seats_available"])
    # Ladder 20: comp allowance.
    if comp_quantity > 0:
        if member is None or member["effective_tier"] not in ("SUPPORTER", "DONOR_CIRCLE"):
            raise ApiError("ERR_COMP_ALLOWANCE_EXCEEDED",
                           "Comps are only for SUPPORTER and DONOR_CIRCLE members.")
        if comp_quantity > quantity or comp_quantity > member["comp_tickets_remaining"]:
            raise ApiError("ERR_COMP_ALLOWANCE_EXCEEDED",
                           "The comp request exceeds the order or the member's allowance.")
    # Ladder 25: the sale dimension must admit orders.
    if showtime["sale_status"] not in ("ON_SALE", "SOLD_OUT"):
        raise ApiError("ERR_SHOWTIME_SALES_CLOSED",
                       "The box office for this screening is not open.")
    # Ladder 27: credit honesty.
    if apply_credit and (member is None or member["credit_balance_cents"] <= 0):
        raise ApiError("ERR_CREDIT_BALANCE_INSUFFICIENT",
                       "Credit redemption needs a member holding credit.")
    pricing = price_order(showtime, member, quantity, comp_quantity, apply_credit)
    row = new_record(
        showtime_id=showtime_id,
        member_id=member_id,
        quantity=quantity,
        comp_quantity=comp_quantity,
        purchaser_email=purchaser_email,
        unit_price_cents=pricing["unit_price_cents"],
        line_subtotal_cents=pricing["line_subtotal_cents"],
        facility_fee_cents=pricing["facility_fee_cents"],
        applied_credit_cents=pricing["applied_credit_cents"],
        total_cents=pricing["total_cents"],
        status="RESERVED",
        refund_destination=None,
        apply_credit=apply_credit,
    )
    insert("orders", row)
    ledger = Ledger()
    if member is not None:
        member["credit_balance_cents"] = (member["credit_balance_cents"]
                                          - pricing["applied_credit_cents"])
        if pricing["applied_credit_cents"] or comp_quantity:
            ledger.mark(member)
    refresh_showtime_rollup(showtime, ledger)
    ledger.flush()
    return object_response(serialize.order(row), 201)


@bp.get("/ticket-orders/<order_id>")
def read_order(order_id):
    role, uid = authorize(ORDER_READ)
    order = must_find("orders", order_id)
    if role == ROLE_MEMBER:
        require_own_member(role, uid, order["member_id"])
    return object_response(serialize.order(order))


@bp.get("/ticket-orders")
def list_orders():
    role, uid = authorize(ORDER_READ)
    found = rows("orders")
    for name in ("showtime_id", "member_id", "status"):
        value = query_str(name)
        if value is not None:
            if name == "member_id" and role == ROLE_MEMBER:
                require_own_member(role, uid, value)
            found = [o for o in found if o[name] == value]
    if role == ROLE_MEMBER:
        found = [o for o in found if o["member_id"] == uid]
    return paged(ordered(found), serialize.order)


@bp.post("/ticket-orders/<order_id>/pay")
def pay_order(order_id):
    role, uid = authorize((ROLE_BOX, ROLE_MEMBER))
    body()
    order = must_find("orders", order_id)
    if role == ROLE_MEMBER:
        require_own_member(role, uid, order["member_id"])
    require_order_state(order, ("RESERVED",))
    showtime = must_find("showtimes", order["showtime_id"])
    if showtime["status"] != "SCHEDULED":
        raise ApiError("ERR_SHOWTIME_INVALID_STATE",
                       "The screening is no longer scheduled.")
    ledger = Ledger()
    order["status"] = "PAID"
    ledger.mark(order)
    refresh_showtime_rollup(showtime, ledger)
    ledger.flush()
    return object_response(serialize.order(order))


@bp.post("/ticket-orders/<order_id>/refund")
def refund_order(order_id):
    authorize((ROLE_BOX, ROLE_EXEC))
    payload = body()
    destination = req_enum(payload, "refund_destination", REFUND_DESTINATIONS)
    order = must_find("orders", order_id)
    require_order_state(order, ("PAID",))
    showtime = must_find("showtimes", order["showtime_id"])
    if showtime["status"] == "COMPLETED":
        raise ApiError("ERR_SHOWTIME_INVALID_STATE",
                       "A completed screening's orders can no longer be refunded.")
    ledger = Ledger()
    order["status"] = "REFUNDED"
    order["refund_destination"] = destination
    ledger.mark(order)
    member = find("members", order["member_id"]) if order["member_id"] else None
    if member is not None:
        if destination == "MEMBER_CREDIT":
            member["credit_balance_cents"] += order["total_cents"]
        member["credit_balance_cents"] += order["applied_credit_cents"]
        ledger.mark(member)
    refresh_showtime_rollup(showtime, ledger)
    ledger.flush()
    return object_response(serialize.order(order))
