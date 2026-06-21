"""Order / ticket / payment endpoints (PRD §3.4–§3.7).

Covers: create HELD order (full validation chain + OCC + member overlap),
pay (final pricing + total + loyalty + wallet + payment), cancel, refund,
exchange, and the reverse-reachability list reads for tickets and payments.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
import errors as E
from middleware import (
    authenticate, authorize, current_role, current_user_id,
    CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404, require_member_owns_resource

bp = Blueprint("orders", __name__)


def _live_member_orders_overlap(member_id, showtime_id, this_starts, this_ends):
    """ERR_MEMBER_DOUBLE_BOOKED: member already holds a live (HELD/PAID) order on
    a DIFFERENT showtime whose half-open interval overlaps this one (zero buffer).
    """
    for order in db.orders.values():
        if order["member_id"] != member_id:
            continue
        if order["showtime_id"] == showtime_id:
            continue
        if order["status"] not in ("HELD", "PAID"):
            continue
        other_st = db.showtimes.get(order["showtime_id"])
        if other_st is None:
            continue
        o_start = C.parse_iso(other_st["starts_at"])
        o_end = C.parse_iso(other_st["ends_at"])
        # Half-open overlap, no buffer.
        if this_starts < o_end and o_start < this_ends:
            return True
    return False


# ============================================================================
# Create a HELD order
# ============================================================================
@bp.route("/showtimes/<st_id>/orders", methods=["POST"])
def create_order(st_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER})

    # priority 4: existence — showtime, then member FK.
    st = get_or_404(db.showtimes, st_id, "Showtime")
    D.expire_showtime_holds(st_id)

    body = C.get_body()
    C.require_fields(body, ["member_id", "seat_ids", "expected_showtime_version"])
    member_id = C.require_str(body, "member_id")

    seat_ids = body.get("seat_ids")
    if not isinstance(seat_ids, list):
        raise E.invalid_request("seat_ids must be an array")

    combo_ids = body.get("combo_ids", [])
    if combo_ids is None:
        combo_ids = []
    if not isinstance(combo_ids, list):
        raise E.invalid_request("combo_ids must be an array")

    apply_wallet = body.get("apply_wallet_credit", False)
    if apply_wallet is None:
        apply_wallet = False
    if not C.is_bool(apply_wallet):
        raise E.invalid_request("apply_wallet_credit must be a boolean")

    expected = body.get("expected_showtime_version")
    if not C.is_int(expected):
        raise E.invalid_request("expected_showtime_version must be an integer")

    member = get_or_404(db.members, member_id, "Member")
    # Existence of FK seats / combos.
    for sid in seat_ids:
        if not C.is_str(sid) or sid not in db.seats:
            raise E.not_found("Seat not found")
    for cid in combo_ids:
        if not C.is_str(cid) or cid not in db.combos:
            raise E.not_found("ConcessionCombo not found")

    # priority 3: ownership — a Member may only act on its own member_id.
    if current_role() == MEMBER and current_user_id() != member_id:
        raise E.not_owner("Member may only create orders for itself")

    # priority 5: state — showtime must be ON_SALE to take orders.
    if st["status"] != "ON_SALE":
        raise E.invalid_state("Showtime must be ON_SALE to create an order")

    # priority 6: OCC
    if expected != st["version"]:
        raise E.APIError(E.ERR_STALE_SHOWTIME_VERSION, 412,
                         "expected_showtime_version does not match current version")

    # ---- business band, in fixed order (PRD §2.7 / §3.4) ----
    # priority 10: every seat belongs to this showtime
    for sid in seat_ids:
        if db.seats[sid]["showtime_id"] != st_id:
            raise E.APIError(E.ERR_SEAT_NOT_ON_SHOWTIME, 422,
                             "A requested seat does not belong to this showtime")

    # priority 11: each seat is FREE
    for sid in seat_ids:
        if D.project_seat(db.seats[sid])["occupancy"] != "FREE":
            raise E.APIError(E.ERR_SEAT_UNAVAILABLE, 409, "A requested seat is unavailable")

    # priority 12: at least one seat
    if len(seat_ids) == 0:
        raise E.APIError(E.ERR_NO_SEATS_SELECTED, 422, "At least one seat must be requested")

    # priority 13: member overlap (zero-buffer, different showtime)
    this_starts = C.parse_iso(st["starts_at"])
    this_ends = C.parse_iso(st["ends_at"])
    if _live_member_orders_overlap(member_id, st_id, this_starts, this_ends):
        raise E.APIError(E.ERR_MEMBER_DOUBLE_BOOKED, 409,
                         "Member already holds a live overlapping order")

    # priority 14: RENTAL cannot be sold per-seat
    if st["rental_basis"] == "RENTAL":
        raise E.APIError(E.ERR_RENTAL_NO_SEAT_SALES, 409,
                         "RENTAL showtime cannot be sold per-seat")

    # ---- place the order ----
    order = C.new_common_fields()
    now = clock.now()
    hold_expires = now + timedelta(minutes=D.HOLD_TTL_MINUTES)
    hold_expires_iso = hold_expires.strftime("%Y-%m-%dT%H:%M:%S.") + f"{hold_expires.microsecond // 1000:03d}Z"
    order.update({
        "showtime_id": st_id,
        "member_id": member_id,
        "seat_ids": list(seat_ids),
        "combo_ids": list(combo_ids),
        "apply_wallet_credit": apply_wallet,
        "status": "HELD",
        "tickets_subtotal_cents": 0,
        "combos_subtotal_cents": 0,
        "wallet_applied_cents": 0,
        "total_charged_cents": 0,
        "hold_expires_at": hold_expires_iso,
        "_accrued_points": 0,
    })

    for sid in seat_ids:
        seat = db.seats[sid]
        provisional = D.seat_price(st, seat)
        ticket = C.new_common_fields()
        ticket.update({
            "order_id": order["id"],
            "showtime_id": st_id,
            "seat_id": sid,
            "member_id": member_id,
            "provisional_price_cents": provisional,
            "final_price_cents": None,
            "state": "HELD",
        })
        db.tickets[ticket["id"]] = ticket
        seat["occupancy"] = "HELD"

    db.orders[order["id"]] = order
    C.touch(st)  # seat counts/version changed
    return response.ok_object(C.serialize(order), 201)


# ============================================================================
# Reads
# ============================================================================
@bp.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER, CINEMA_MANAGER})
    order = get_or_404(db.orders, order_id, "Order")
    require_member_owns_resource(order["member_id"])
    D.maybe_expire_order(order)
    return response.ok_object(C.serialize(order), 200)


@bp.route("/orders", methods=["GET"])
def list_orders():
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER, CINEMA_MANAGER})
    limit, offset = C.parse_pagination()
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    # Lazily expire across the board so listed statuses reflect the hold clock.
    D.expire_sweep()
    items = list(db.orders.values())
    if current_role() == MEMBER:
        items = [o for o in items if o["member_id"] == current_user_id()]
    if member_id is not None:
        items = [o for o in items if o["member_id"] == member_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/orders/<order_id>/tickets", methods=["GET"])
def list_order_tickets(order_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER, CINEMA_MANAGER})
    order = get_or_404(db.orders, order_id, "Order")
    require_member_owns_resource(order["member_id"])
    limit, offset = C.parse_pagination()
    state = request.args.get("state")
    items = [t for t in db.tickets.values() if t["order_id"] == order_id]
    if state is not None:
        items = [t for t in items if t["state"] == state]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/orders/<order_id>/payments", methods=["GET"])
def list_order_payments(order_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, CINEMA_MANAGER})
    get_or_404(db.orders, order_id, "Order")
    limit, offset = C.parse_pagination()
    items = [p for p in db.payments.values() if p["order_id"] == order_id]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


# ============================================================================
# Pay
# ============================================================================
@bp.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER})
    order = get_or_404(db.orders, order_id, "Order")
    require_member_owns_resource(order["member_id"])

    # Lazily expire first so a past-TTL order pays as INVALID_STATE.
    D.maybe_expire_order(order)

    # priority 5: state — must be HELD and not past TTL; showtime ON_SALE; seats still held.
    if order["status"] != "HELD":
        raise E.invalid_state("Order must be HELD to pay")
    if clock.now() >= C.parse_iso(order["hold_expires_at"]):
        raise E.invalid_state("Order hold has expired")
    st = db.showtimes.get(order["showtime_id"])
    if st is None or st["status"] != "ON_SALE":
        raise E.invalid_state("Showtime must be ON_SALE to pay")
    tickets = D.order_tickets(order_id)
    for t in tickets:
        seat = db.seats.get(t["seat_id"])
        if seat is None or t["state"] != "HELD":
            raise E.invalid_state("A seat in this order is no longer held by it")

    member = db.members[order["member_id"]]

    # priority 15: wallet over-claim guard.
    # Final prices first (PRD §3.5 pinned order).
    tickets_subtotal = 0
    for t in tickets:
        final = D.seat_price(st, db.seats[t["seat_id"]])
        t["final_price_cents"] = final
        t["state"] = "SOLD"
        C.touch(t)
        db.seats[t["seat_id"]]["occupancy"] = "SOLD"
        tickets_subtotal += final

    combos_subtotal = D.compute_combos_subtotal(member, order["combo_ids"])
    gross_due = tickets_subtotal + combos_subtotal

    if order["apply_wallet_credit"]:
        balance = member.get("wallet_credit_cents", 0)
        if balance <= 0:
            raise E.APIError(E.ERR_INSUFFICIENT_WALLET_CREDIT, 422,
                             "No wallet credit available to apply")
        wallet_applied = min(balance, gross_due)
    else:
        wallet_applied = 0

    total_charged = gross_due - wallet_applied

    order["tickets_subtotal_cents"] = tickets_subtotal
    order["combos_subtotal_cents"] = combos_subtotal
    order["wallet_applied_cents"] = wallet_applied
    order["total_charged_cents"] = total_charged
    order["status"] = "PAID"

    # Payment
    payment = C.new_common_fields()
    payment.update({
        "order_id": order_id,
        "amount_cents": total_charged,
        "refunded_cents": 0,
        "status": "CAPTURED",
    })
    db.payments[payment["id"]] = payment

    # Debit wallet (no version bump here; apply_points_delta touches member once).
    if wallet_applied > 0:
        member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) - wallet_applied

    # Loyalty accrual + tier re-derive (also refreshes member updated_at/version).
    points = D.points_for_subtotal(tickets_subtotal)
    order["_accrued_points"] = points
    D.apply_points_delta(member, points)

    C.touch(order)
    C.touch(st)
    return response.ok_object(C.serialize(order), 200)


# ============================================================================
# Cancel (HELD)
# ============================================================================
@bp.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT, MEMBER})
    order = get_or_404(db.orders, order_id, "Order")
    require_member_owns_resource(order["member_id"])
    D.maybe_expire_order(order)
    if order["status"] != "HELD":
        raise E.invalid_state("Order must be HELD to cancel")
    order["status"] = "CANCELLED"
    D._void_tickets_and_free_seats(order)
    C.touch(order)
    st = db.showtimes.get(order["showtime_id"])
    if st is not None:
        C.touch(st)
    return response.ok_object(C.serialize(order), 200)


# ============================================================================
# Refund (PAID)
# ============================================================================
@bp.route("/orders/<order_id>/refund", methods=["POST"])
def refund_order(order_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT})
    order = get_or_404(db.orders, order_id, "Order")
    if order["status"] != "PAID":
        raise E.invalid_state("Order must be PAID to refund")

    st = db.showtimes.get(order["showtime_id"])
    # priority 16: refund only before starts_at, while ON_SALE or CANCELLED.
    if st is not None:
        if st["status"] not in ("ON_SALE", "CANCELLED") or clock.now() >= C.parse_iso(st["starts_at"]):
            raise E.APIError(E.ERR_PAST_SHOWTIME, 409,
                             "Refund only allowed before the showtime starts")

    body = C.get_body()
    C.require_fields(body, ["refund_destination"])
    destination = body.get("refund_destination")
    if destination not in ("ORIGINAL", "WALLET"):
        raise E.invalid_request("refund_destination must be ORIGINAL or WALLET")

    D.refund_paid_order(order, destination, from_cascade=False)
    return response.ok_object(C.serialize(order), 200)


# ============================================================================
# Exchange (PAID -> EXCHANGED, successor HELD order)
# ============================================================================
@bp.route("/orders/<order_id>/exchange", methods=["POST"])
def exchange_order(order_id):
    role = authenticate()
    authorize(role, {BOX_OFFICE_AGENT})
    order = get_or_404(db.orders, order_id, "Order")
    if order["status"] != "PAID":
        raise E.invalid_state("Order must be PAID to exchange")

    old_st = db.showtimes.get(order["showtime_id"])
    # priority 16: before the original showtime's start.
    if old_st is not None and clock.now() >= C.parse_iso(old_st["starts_at"]):
        raise E.APIError(E.ERR_PAST_SHOWTIME, 409,
                         "Exchange only allowed before the showtime starts")

    body = C.get_body()
    C.require_fields(body, ["new_showtime_id", "new_seat_ids"])
    new_st_id = C.require_str(body, "new_showtime_id")
    new_seat_ids = body.get("new_seat_ids")
    if not isinstance(new_seat_ids, list):
        raise E.invalid_request("new_seat_ids must be an array")

    # existence
    new_st = get_or_404(db.showtimes, new_st_id, "Showtime")
    for sid in new_seat_ids:
        if not C.is_str(sid) or sid not in db.seats:
            raise E.not_found("Seat not found")

    # target showtime must be ON_SALE and before its start.
    if new_st["status"] != "ON_SALE" or clock.now() >= C.parse_iso(new_st["starts_at"]):
        raise E.invalid_state("Target showtime must be ON_SALE and not yet started")

    # business band on the target seats (same relative order as create).
    for sid in new_seat_ids:
        if db.seats[sid]["showtime_id"] != new_st_id:
            raise E.APIError(E.ERR_SEAT_NOT_ON_SHOWTIME, 422,
                             "A requested seat does not belong to the target showtime")
    for sid in new_seat_ids:
        if D.project_seat(db.seats[sid])["occupancy"] != "FREE":
            raise E.APIError(E.ERR_SEAT_UNAVAILABLE, 409, "A requested seat is unavailable")
    if len(new_seat_ids) == 0:
        raise E.APIError(E.ERR_NO_SEATS_SELECTED, 422, "At least one seat must be requested")

    member = db.members[order["member_id"]]
    old_subtotal = order.get("tickets_subtotal_cents", 0)

    # --- old order EXCHANGED: void tickets, free seats, reverse loyalty ---
    order["status"] = "EXCHANGED"
    D._void_tickets_and_free_seats(order)
    apply_old_points = order.get("_accrued_points", 0)

    # --- successor HELD order on target ---
    successor = C.new_common_fields()
    now = clock.now()
    hold_expires = now + timedelta(minutes=D.HOLD_TTL_MINUTES)
    hold_expires_iso = hold_expires.strftime("%Y-%m-%dT%H:%M:%S.") + f"{hold_expires.microsecond // 1000:03d}Z"

    new_tickets_subtotal = 0
    successor.update({
        "showtime_id": new_st_id,
        "member_id": order["member_id"],
        "seat_ids": list(new_seat_ids),
        "combo_ids": [],
        "apply_wallet_credit": False,
        "status": "HELD",
        "tickets_subtotal_cents": 0,
        "combos_subtotal_cents": 0,
        "wallet_applied_cents": 0,
        "total_charged_cents": 0,
        "hold_expires_at": hold_expires_iso,
        "_accrued_points": 0,
    })
    for sid in new_seat_ids:
        seat = db.seats[sid]
        provisional = D.seat_price(new_st, seat)
        ticket = C.new_common_fields()
        ticket.update({
            "order_id": successor["id"],
            "showtime_id": new_st_id,
            "seat_id": sid,
            "member_id": order["member_id"],
            "provisional_price_cents": provisional,
            "final_price_cents": None,
            "state": "HELD",
        })
        db.tickets[ticket["id"]] = ticket
        seat["occupancy"] = "HELD"
        new_tickets_subtotal += provisional

    # Price difference: new > old -> delta due on successor; new < old -> wallet credit.
    delta = new_tickets_subtotal - old_subtotal
    if delta > 0:
        successor["_amount_due_cents"] = delta
        successor["amount_due_cents"] = delta
    elif delta < 0:
        member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) + (-delta)

    db.orders[successor["id"]] = successor

    # reverse old order's loyalty
    D.apply_points_delta(member, -apply_old_points)

    C.touch(order)
    C.touch(old_st) if old_st is not None else None
    C.touch(new_st)
    return response.ok_object(C.serialize(order), 200)
