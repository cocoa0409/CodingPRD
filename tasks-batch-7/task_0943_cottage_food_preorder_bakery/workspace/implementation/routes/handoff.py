"""Handoff scheduling, the outcome record, and the order/order-line reads."""

from datetime import timedelta

from flask import Blueprint

import config
from db import DB, touch
from errors import ApiError
from ladder import endpoint
from response import ok
from routes.common import list_endpoint
from serialize import dump
from services import money, pricing
from services.gates import active_payment, require_state, window_locked_gate
from tsutil import gte, lt, ts_shift

bp = Blueprint("handoff", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER


def lines_of(order_id):
    return [l for l in DB.values("order_lines") if l.get("order_id") == order_id]


def labels_of_line(line_id):
    return [l for l in DB.values("labels") if l.get("order_line_id") == line_id]


# ---------------------------------------------------------------------------
# POST /bakery/orders/{order_id}/schedule-handoff
# ---------------------------------------------------------------------------

@bp.post("/bakery/orders/<order_id>/schedule-handoff")
@endpoint(roles=[CUSTOMER, BAKER], path=("order_id",))
def schedule_handoff(ctx):
    order = ctx.p["order_id"]
    window = DB.get("offer_windows", order.get("offer_window_id"))
    fks = ctx.body_fks(optional=("delivery_route_id",))              # rung 10
    ctx.ownership(customer_id=order.get("customer_id"),              # rungs 11,12
                  baker_id=(window or {}).get("baker_id"))
    # rung 13 -- the request may carry the two porch flags to satisfy 31/32
    req_unattended = ctx.opt_bool("unattended_consent", None)
    req_cooler = ctx.opt_bool("cooler_provided", None)
    # rung 15 does NOT apply to handoff scheduling.
    window_locked_gate(window)                                       # rung 16
    current = order.get("handoff_status")                            # rung 19
    require_state(current, ("NOT_SCHEDULED", "MISSED"), "handoff_status")
    if current == "NOT_SCHEDULED":
        # READY is admitted alongside CONFIRMED and IN_PRODUCTION.  PRD 3.8
        # states outright that an order moves SCHEDULED -> PICKUP_READY "when
        # the window is *already* HANDOFF_OPEN at the moment of scheduling,
        # within the scheduling request itself" -- and by then every order on
        # the window has advanced to READY.  Restricting the source order status
        # to the scaffold's narrower {CONFIRMED, IN_PRODUCTION} would make that
        # declared branch unreachable from NOT_SCHEDULED altogether, and would
        # leave any order that reached READY unscheduled unable ever to be
        # handed off, stranding rungs 35 and 39 with it.  PRD prose wins over
        # the narrower scaffold precondition list.
        if order.get("order_status") not in ("CONFIRMED", "IN_PRODUCTION", "READY"):
            raise ApiError("ERR_INVALID_STATE",
                           "Scheduling requires a CONFIRMED, IN_PRODUCTION or "
                           "READY order.")
    else:
        if order.get("order_status") != "READY":
            raise ApiError("ERR_INVALID_STATE",
                           "A rebook requires a READY order.")

    mode = order.get("handoff_mode")
    effective_unattended = (order.get("unattended_consent")
                            if req_unattended is None else req_unattended)
    effective_cooler = (order.get("cooler_provided")
                        if req_cooler is None else req_cooler)
    if mode == "PORCH_SELF_SERVE":
        if effective_unattended is not True:                         # rung 31
            raise ApiError("ERR_UNATTENDED_CONSENT_REQUIRED",
                           "Unattended porch handoff requires consent.")
        temp_sensitive = False
        for line in lines_of(order["id"]):
            if line.get("line_status") != "PENDING":
                continue
            item = DB.get("menu_items", line.get("menu_item_id"))
            if item is not None and item.get("temp_sensitive"):
                temp_sensitive = True
                break
        if temp_sensitive and effective_cooler is not True:           # rung 32
            raise ApiError("ERR_COOLER_CONSENT_REQUIRED",
                           "A cooler must be provided for this porch handoff.")
    if mode == "DELIVERY":
        customer = DB.get("customers", order.get("customer_id"))
        baker = DB.get("bakers", (window or {}).get("baker_id"))
        distance = (customer or {}).get("delivery_distance_km")
        radius = (baker or {}).get("permitted_radius_km")
        if distance is None or radius is None or float(distance) > float(radius):
            raise ApiError("ERR_OUT_OF_PERMITTED_ZONE",              # rung 33
                           "The delivery distance leaves the permitted radius.")
    if current == "MISSED":                                          # rung 45
        if ((order.get("rebook_count") or 0) >= config.MISSED_REBOOK_MAX
                or order.get("forfeit_latched")):
            raise ApiError("ERR_REBOOK_LIMIT_EXCEEDED",
                           "The rebook limit has been reached.")
    if mode == "DELIVERY":                                           # rung 47
        if (order.get("subtotal_cents") or 0) < config.DELIVERY_MINIMUM_CENTS:
            raise ApiError("ERR_DELIVERY_MINIMUM_NOT_MET",
                           "The delivery minimum of %d cents is not met."
                           % config.DELIVERY_MINIMUM_CENTS)

    # ---- commit ---------------------------------------------------------
    if req_unattended is not None:
        order["unattended_consent"] = req_unattended
    if req_cooler is not None:
        order["cooler_provided"] = req_cooler
    if current == "MISSED":
        order["rebook_count"] = (order.get("rebook_count") or 0) + 1
    order["handoff_status"] = "SCHEDULED"
    if mode == "DELIVERY" and fks.get("delivery_route_id") is not None:
        order["delivery_route_id"] = fks["delivery_route_id"]["id"]
    # the second step inside the same request: a pickup order scheduled while
    # the window is ALREADY HANDOFF_OPEN becomes collectable at once.  This is
    # what makes a SECOND miss -- and therefore rung 45 -- reachable.
    if (window is not None and window.get("window_status") == "HANDOFF_OPEN"
            and mode in ("PICKUP_COUNTER", "PORCH_SELF_SERVE")):
        order["handoff_status"] = "PICKUP_READY"
    touch(order, ctx.now)
    return ok(dump("orders", order))


# ---------------------------------------------------------------------------
# POST /bakery/orders/{order_id}/handoff-outcome
# ---------------------------------------------------------------------------

@bp.post("/bakery/orders/<order_id>/handoff-outcome")
@endpoint(roles=[BAKER], path=("order_id",))
def handoff_outcome(ctx):
    # CARVE-OUT: rung 16 never applies -- an outcome is legal only once the
    # window is locked or later.
    order = ctx.p["order_id"]
    window = DB.get("offer_windows", order.get("offer_window_id"))
    ctx.ownership(baker_id=(window or {}).get("baker_id"))           # rung 12
    if ctx.body.get("outcome") is None:                              # rung 13
        raise ApiError("ERR_VALIDATION", "outcome is required.")
    outcome = ctx.enum("outcome", "handoff_outcome")                  # rung 14
    current = order.get("handoff_status")

    if outcome == "HANDED_OFF":                                      # rung 19
        require_state(current, ("PICKUP_READY", "OUT_FOR_DELIVERY"),
                      "handoff_status")
        require_state(order.get("order_status"), ("READY",), "order_status")
        for line in lines_of(order["id"]):                           # rung 35
            if line.get("line_status") in ("RELEASED", "RECALL_VOID"):
                continue
            issued = [l for l in labels_of_line(line["id"])
                      if l.get("label_status") == "ISSUED"]
            if not issued:
                raise ApiError("ERR_LABEL_SUPERSEDED",
                               "A live order line lacks an ISSUED label.")
        if order.get("handoff_mode") in ("PICKUP_COUNTER", "PORCH_SELF_SERVE"):
            deadline = order.get("pickup_forfeit_at")                # rung 39
            if deadline is None or not lt(ctx.now, deadline):
                raise ApiError("ERR_PICKUP_GRACE_EXPIRED",
                               "The pickup grace period has expired.")
        _hand_off(order, ctx.now)

    elif outcome == "MISSED":
        require_state(current, ("PICKUP_READY", "OUT_FOR_DELIVERY"),
                      "handoff_status")
        order["handoff_status"] = "MISSED"
        touch(order, ctx.now)

    else:  # FORFEITED
        require_state(current, ("MISSED",), "handoff_status")
        require_state(order.get("order_status"), ("READY",), "order_status")
        # Adjudication of friction 11: forfeiture is admitted for the PICKUP
        # pipeline ONLY.  The order-axis READY -> FORFEITED transition names the
        # mode restriction explicitly, and pickup_forfeit_at -- the deadline the
        # handoff-axis move compares against -- is null for a delivery order.
        # Admitting a delivery forfeiture would either require inventing a
        # comparison against a null deadline or would move handoff_status to
        # FORFEITED while order_status could not follow, producing an undeclared
        # pairing.  Refusing it strands nothing: FORFEITED stays reachable on
        # both axes through the two pickup modes.
        if order.get("handoff_mode") not in ("PICKUP_COUNTER", "PORCH_SELF_SERVE"):
            raise ApiError("ERR_INVALID_STATE",
                           "Only a counter-pickup or porch order may be forfeited.")
        deadline = order.get("pickup_forfeit_at")
        if deadline is None or not gte(ctx.now, deadline):
            raise ApiError("ERR_INVALID_STATE",
                           "The pickup grace period has not yet expired.")
        order["handoff_status"] = "FORFEITED"
        order["order_status"] = "FORFEITED"
        order["forfeit_latched"] = True
        # FORFEIT_REFUND_PCT is 0.00 -- nothing is refunded.
        touch(order, ctx.now)
        baker = DB.get("bakers", (window or {}).get("baker_id"))
        if baker is not None:
            money.refresh_gross_sales(baker)
            money.refresh_payout_net(baker)
            touch(baker, ctx.now)
    return ok(dump("orders", order))


def _hand_off(order, now):
    order["handoff_status"] = "HANDED_OFF"
    order["order_status"] = "FULFILLED"
    order["fulfilled_at"] = now
    order["review_window_closes_at"] = ts_shift(
        now, timedelta(days=config.REVIEW_WINDOW_DAYS))
    for line in lines_of(order["id"]):
        if line.get("line_status") not in ("ALLOCATED", "CREDITED"):
            continue
        line["line_status"] = "FULFILLED"
        touch(line, now)
        for label in labels_of_line(line["id"]):
            if label.get("label_status") == "ISSUED":
                label["label_status"] = "CONSUMED"
                touch(label, now)
    touch(order, now)
    pay = active_payment(order["id"])
    if pay is not None and pay.get("payment_state") == "CAPTURED":
        pay["payment_state"] = "SETTLED"
        touch(pay, now)
    baker = money.baker_of_order(order)
    if baker is not None:
        money.refresh_gross_sales(baker)
        money.refresh_payout_net(baker)
        touch(baker, now)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.get("/bakery/orders/<order_id>")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("order_id",))
def read_order(ctx):
    order = ctx.p["order_id"]
    window = DB.get("offer_windows", order.get("offer_window_id"))
    ctx.ownership(customer_id=order.get("customer_id"),
                  baker_id=(window or {}).get("baker_id"))
    return ok(dump("orders", order))


@bp.get("/bakery/orders")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], list_ep=True)
def list_orders(ctx):
    return list_endpoint(ctx, "orders", {
        "customer_id": "customer_id",
        "offer_window_id": "offer_window_id",
        "subscription_cycle_id": "subscription_cycle_id",
        "delivery_route_id": "delivery_route_id",
        "order_status": "order_status",
        "payment_status": "payment_status",
        "handoff_status": "handoff_status",
    })


@bp.get("/bakery/orders/<order_id>/quote")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("order_id",))
def read_quote(ctx):
    order = ctx.p["order_id"]
    window = DB.get("offer_windows", order.get("offer_window_id"))
    ctx.ownership(customer_id=order.get("customer_id"),
                  baker_id=(window or {}).get("baker_id"))
    return ok(pricing.quote(order))


@bp.get("/bakery/order-lines/<order_line_id>")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("order_line_id",))
def read_line(ctx):
    line = ctx.p["order_line_id"]
    order = DB.get("orders", line.get("order_id"))
    window = DB.get("offer_windows", (order or {}).get("offer_window_id"))
    ctx.ownership(customer_id=(order or {}).get("customer_id"),
                  baker_id=(window or {}).get("baker_id"))
    return ok(dump("order_lines", line))


@bp.get("/bakery/order-lines")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], list_ep=True)
def list_lines(ctx):
    return list_endpoint(ctx, "order_lines", {
        "order_id": "order_id",
        "menu_item_id": "menu_item_id",
        "batch_id": "batch_id",
        "line_status": "line_status",
    })
