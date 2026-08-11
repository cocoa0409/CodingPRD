"""Courier legs and the append-only chain of custody."""
from flask import Blueprint

import serializers
import store
import validation
from calendar_util import is_business_day
from constants import (
    API_PREFIX,
    COURIER_REDISPATCH_CAP,
    LEG_FROM_HOLDERS,
    LEG_OUTCOMES,
    LEG_TO_HOLDERS,
)
from errors import fail
from routes.common import READ_ROLES, created, endpoint, listing, ok
from services import custody, lookup, money, readiness
from validation import Body

bp = Blueprint("courier", __name__)
P = API_PREFIX


@bp.route(P + "/orders/<order_id>/courier-legs", methods=["POST"])
@endpoint("orders.courier_legs.create", ["CourierOps"])
def create_leg(ctx, order_id):
    order = validation.need_order(order_id)
    body = Body(ctx.body)
    leg_index = body.integer("leg_index", minimum=1)
    from_holder = body.enum("from_holder", LEG_FROM_HOLDERS)
    to_holder = body.enum("to_holder", LEG_TO_HOLDERS)
    scheduled_date = body.date("scheduled_date")
    body.check()
    validation.guard_order(ctx, order)

    row = store.insert("courier_legs", {
        "order_id": order["id"],
        "leg_index": leg_index,
        "from_holder": from_holder,
        "to_holder": to_holder,
        "scheduled_date": scheduled_date,
        "leg_status": "CREATED",
        "attempt_count": 0,
    })
    return created(serializers.courier_leg(row))


@bp.route(P + "/orders/<order_id>/courier-legs", methods=["GET"])
@endpoint("orders.courier_legs.list", READ_ROLES)
def list_legs(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    rows = lookup.legs_of(order)
    rows = validation.apply_filter(rows, "leg_status")
    return listing(rows, serializers.courier_leg)


@bp.route(P + "/courier-legs/<leg_id>/dispatch", methods=["POST"])
@endpoint("courier_legs.dispatch", ["CourierOps"])
def dispatch_leg(ctx, leg_id):
    leg = validation.need("courier_legs", leg_id)
    order = lookup.order_of_leg(leg)
    Body(ctx.body).check()
    validation.guard_order(ctx, order)
    validation.require_state(leg["leg_status"], ("CREATED", "FAILED"))
    # Rung 14
    if order["custody_holder"] != leg["from_holder"]:
        fail("ERR_CUSTODY_MISMATCH")
    # Rung 15
    pending = [l for l in lookup.legs_of(order) if l["leg_status"] in ("CREATED", "FAILED")]
    lowest = min(l["leg_index"] for l in pending)
    if leg["leg_index"] != lowest:
        fail("ERR_LEG_SEQUENCE_VIOLATION")
    # Rung 16
    consulate = lookup.consulate_of(order)
    if not is_business_day(leg["scheduled_date"], consulate):
        fail("ERR_EMBASSY_CLOSED")
    # Rung 25
    if leg["attempt_count"] >= 1 + COURIER_REDISPATCH_CAP:
        fail("ERR_COURIER_ATTEMPT_CAP_EXCEEDED")

    leg["attempt_count"] += 1
    leg["leg_status"] = "DISPATCHED"
    store.touch(leg)
    reason = "DECISION_RETURNED" if leg["from_holder"] == "AGENCY" else "LEG_DISPATCHED"
    custody.handover(order, "COURIER", reason, leg_index=leg["leg_index"])
    store.touch(order)
    readiness.reevaluate_gate(order, bump=False)
    return ok(serializers.courier_leg(leg))


@bp.route(P + "/courier-legs/<leg_id>/complete", methods=["POST"])
@endpoint("courier_legs.complete", ["CourierOps"])
def complete_leg(ctx, leg_id):
    leg = validation.need("courier_legs", leg_id)
    order = lookup.order_of_leg(leg)
    body = Body(ctx.body)
    outcome = body.enum("outcome", LEG_OUTCOMES)
    body.check()
    validation.guard_order(ctx, order)
    validation.require_state(leg["leg_status"], ("DISPATCHED",))

    if outcome == "DELIVERED":
        leg["leg_status"] = "DELIVERED"
        store.touch(leg)
        custody.handover(order, leg["to_holder"], "LEG_DELIVERED")
        if leg["to_holder"] == "SERVICE" and order["payment_status"] == "REFUND_PENDING":
            money.disburse_scheduled_refund(order)
        store.touch(order)
        for applicant in lookup.applicants_of(order):
            readiness.recompute_readiness(applicant)
        readiness.reevaluate_gate(order, bump=False)
    else:
        leg["leg_status"] = "FAILED"
        store.touch(leg)
        custody.handover(order, leg["from_holder"], "LEG_FAILED_RETURN")
        store.touch(order)
        readiness.reevaluate_gate(order, bump=False)
    return ok(serializers.courier_leg(leg))


@bp.route(P + "/orders/<order_id>/custody-events", methods=["GET"])
@endpoint("orders.custody_events", READ_ROLES)
def list_custody_events(ctx, order_id):
    order = validation.need_order(order_id)
    validation.check_membership(ctx, order)
    return listing(lookup.custody_events_of(order), serializers.custody_event)
