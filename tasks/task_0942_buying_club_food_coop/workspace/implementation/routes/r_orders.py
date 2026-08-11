"""Member orders: the fulfilment axis and the money axis (8 endpoints)."""

from flask import Blueprint

from core import serialize
from core.constants import (ORDER_STATUSES, PAYMENT_STATUSES, REFUND_DESTINATIONS,
                            ROLES, SIMULATED_OUTCOMES)
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_body, enum_filter, free_filter,
                         gate_cycle_closed, gate_cycle_lock, gate_membership,
                         gate_posted_ledger, pagination, path_row, req_id, req_int,
                         rung_cutoff, rung_order_owner)
from core.store import DB, touch
from services import commission, credits, cycle_ops, payments, reconciliation, recompute
from services.droprun_ops import new_order_fields
from services.lock_cascade import cancel_lines

bp = Blueprint("orders", __name__)
R5 = list(ROLES)


def _cycle_of_order(order):
    drop_run = DB.get("DropRun", order["drop_run_id"])
    return DB.get("Cycle", drop_run["cycle_id"]) if drop_run else None


@bp.post("/member-orders")
@endpoint(["ClubAdmin", "Member"])
def create_member_order(ctx):
    member = body_fk(ctx, "member_id")                     # rung 5
    drop_run = body_fk(ctx, "drop_run_id")
    req_id(ctx, "member_id")                               # rung 7
    req_id(ctx, "drop_run_id")
    gate_cycle_closed(drop_run)                            # rung 9
    gate_membership(member)                                # rung 10
    cycle = DB.get("Cycle", drop_run["cycle_id"])
    gate_cycle_lock(cycle)                                 # rung 13
    rung_cutoff(cycle)                                     # rung 14
    for existing in recompute.orders_of_drop_run(drop_run):     # rung 35
        if existing["member_id"] == member["id"] and existing["status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_ORDER_FOR_MEMBER")
    row = DB.insert("MemberOrder", new_order_fields(member["id"], drop_run["id"]))
    return created(serialize.member_order(row))


@bp.get("/member-orders")
@endpoint(R5)
def list_member_orders(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", ORDER_STATUSES)
    payment_status = enum_filter(ctx, "payment_status", PAYMENT_STATUSES)
    member_id = free_filter(ctx, "member_id")
    drop_run_id = free_filter(ctx, "drop_run_id")
    rows = []
    for row in DB.all("MemberOrder"):
        if member_id is not None and row["member_id"] != member_id:
            continue
        if drop_run_id is not None and row["drop_run_id"] != drop_run_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if payment_status is not None and row["payment_status"] != payment_status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/member-orders/<member_order_id>")
@endpoint(R5)
def read_member_order(ctx, member_order_id):
    return ok(serialize.member_order(path_row("member_order_id", member_order_id)))


@bp.post("/member-orders/<member_order_id>/submit")
@endpoint(["ClubAdmin", "Member"])
def submit_member_order(ctx, member_order_id):
    order = path_row("member_order_id", member_order_id)   # rung 4
    member = DB.get("Member", order["member_id"])
    gate_cycle_closed(order)                               # rung 9
    gate_membership(member)                                # rung 10
    cycle = _cycle_of_order(order)
    gate_cycle_lock(cycle)                                 # rung 13
    rung_cutoff(cycle)                                     # rung 14
    if order["status"] != "DRAFT":                         # rung 16
        raise ApiError("ERR_INVALID_ORDER_STATE")
    rung_order_owner(ctx, order)                           # rung 26
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_LAPSED",
                       "The ordering member's status is not ACTIVE.")
    requested = [l for l in recompute.lines_of_order(order) if l["status"] == "REQUESTED"]
    if not requested:
        raise ApiError("ERR_VALIDATION", "The order carries no REQUESTED line.")
    order["status"] = "SUBMITTED"
    touch(order)
    recompute.recompute_live_drop_subtotal(DB.get("DropRun", order["drop_run_id"]))
    return ok(serialize.member_order(order))


@bp.post("/member-orders/<member_order_id>/cancel")
@endpoint(["ClubAdmin", "Member"])
def cancel_member_order(ctx, member_order_id):
    order = path_row("member_order_id", member_order_id)   # rung 4
    gate_cycle_closed(order)                               # rung 9
    cycle = _cycle_of_order(order)
    gate_cycle_lock(cycle)                                 # rung 13
    if order["status"] not in ("DRAFT", "SUBMITTED"):      # rung 16
        raise ApiError("ERR_INVALID_ORDER_STATE")
    rung_order_owner(ctx, order)                           # rung 26
    order["status"] = "CANCELLED"
    cycle_ops.void_authorizations(order)
    touch(order)
    cancel_lines(order, ("REQUESTED",))
    recompute.recompute_live_drop_subtotal(DB.get("DropRun", order["drop_run_id"]))
    return ok(serialize.member_order(order))


@bp.post("/member-orders/<member_order_id>/authorize")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def authorize_member_order(ctx, member_order_id):
    order = path_row("member_order_id", member_order_id)   # rung 4
    outcome = enum_body(ctx, "simulated_outcome", SIMULATED_OUTCOMES,
                        default="SUCCEEDED")               # rung 8
    gate_cycle_closed(order)                               # rung 9
    if order["status"] not in payments.AUTHORIZE_FULFILMENT_STATES:   # rung 16
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if outcome == "SUCCEEDED":
        if order["payment_status"] not in ("UNPAID", "AUTH_FAILED"):
            raise ApiError("ERR_INVALID_ORDER_STATE")
    elif order["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    cycle = _cycle_of_order(order)
    # FRICTION 2 — only the UNPAID -> AUTHORIZED leg declares a cycle-status
    # precondition; the failing leg and the retry leg deliberately declare none.
    if outcome == "SUCCEEDED" and order["payment_status"] == "UNPAID":
        if cycle is None or cycle["status"] not in payments.AUTHORIZE_CYCLE_STATES:
            raise ApiError("ERR_INVALID_CYCLE_STATE")
    estimated_total, authorized = payments.authorization_estimate(order)
    order["estimated_total_cents"] = estimated_total
    if outcome == "SUCCEEDED":
        payments.create_payment(order, "AUTHORIZATION", "CARD", authorized, "SUCCEEDED")
        order["authorized_amount_cents"] = authorized
        order["payment_status"] = "AUTHORIZED"
    else:
        payments.create_payment(order, "AUTHORIZATION", "CARD", authorized, "FAILED")
        order["authorized_amount_cents"] = 0
        order["payment_status"] = "AUTH_FAILED"
    touch(order)
    return ok(serialize.member_order(order))


@bp.post("/member-orders/<member_order_id>/capture")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def capture_member_order(ctx, member_order_id):
    order = path_row("member_order_id", member_order_id)   # rung 4
    apply_credit = None
    if "apply_credit_cents" in ctx.body and ctx.body["apply_credit_cents"] is not None:
        apply_credit = req_int(ctx, "apply_credit_cents", minimum=0)   # rung 7
    gate_cycle_closed(order)                               # rung 9
    if order["status"] not in payments.CAPTURE_FULFILMENT_STATES:      # rung 16
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    cycle = _cycle_of_order(order)
    if cycle is None or cycle["status"] not in payments.CAPTURE_CYCLE_STATES:
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    figures = payments.capture_figures(order)
    if apply_credit is not None and apply_credit > figures["credit_cap"]:   # rung 51
        raise ApiError("ERR_CREDIT_CAP_EXCEEDED")
    credits.sweep(order["member_id"])
    # FRICTION 6 — STEP 6 of member_order_totals: the wanted amount is
    # apply_credit_cents when supplied, and the credit cap otherwise.
    want = apply_credit if apply_credit is not None else figures["credit_cap"]
    want = min(want, figures["credit_cap"])
    projected_credit = min(want, credits.available(order["member_id"]))
    projected_actual = figures["pre_credit_total_cents"] - projected_credit
    variance = projected_actual - order["authorized_amount_cents"]
    if variance > payments.variance_band(order["authorized_amount_cents"]):   # rung 52
        raise ApiError("ERR_PAYMENT_VARIANCE_EXCEEDED")
    credit_applied = credits.draw(order["member_id"], want)
    payments.commit_capture(order, figures, credit_applied)
    return ok(serialize.member_order(order))


@bp.post("/member-orders/<member_order_id>/refund")
@endpoint(["ClubAdmin", "FinanceOfficer"])
def refund_member_order(ctx, member_order_id):
    order = path_row("member_order_id", member_order_id)   # rung 4
    amount_cents = req_int(ctx, "amount_cents")            # rung 7
    if "destination" not in ctx.body or ctx.body["destination"] is None:
        raise ApiError("ERR_VALIDATION", "destination is required.")
    destination = enum_body(ctx, "destination", REFUND_DESTINATIONS, required=True)  # rung 8
    gate_cycle_closed(order)                               # rung 9
    drop_run = DB.get("DropRun", order["drop_run_id"])
    gate_posted_ledger(drop_run)                           # rung 12
    if order["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):   # rung 16
        raise ApiError("ERR_INVALID_ORDER_STATE")
    outstanding = order["captured_cents"] - order["refunded_cents"]
    if amount_cents < 1 or amount_cents > outstanding:     # rung 53
        raise ApiError("ERR_REFUND_EXCEEDS_CAPTURE")

    # HOP 1 — the refund payment.
    payments.create_payment(order, "REFUND", destination, amount_cents, "SUCCEEDED")
    # HOP 2 — the order's money axis moves.
    order["refunded_cents"] += amount_cents
    order["payment_status"] = ("REFUNDED"
                               if order["refunded_cents"] >= order["captured_cents"]
                               else "PARTIALLY_REFUNDED")
    touch(order)
    if destination == "STORE_CREDIT":
        credits.mint(order["member_id"], amount_cents, credits.default_expiry_iso(),
                     "REFUND", source_member_order_id=order["id"])
    # HOPS 3 and 4 — commission clawback, then the drop's ledger.
    if drop_run is not None:
        commission.adjust_for_refund(drop_run, amount_cents)
        reconciliation.recompute_downstream(drop_run)
    return ok(serialize.member_order(order))
