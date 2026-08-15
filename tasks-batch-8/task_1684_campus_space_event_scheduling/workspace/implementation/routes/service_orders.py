"""Service orders (PRD 3.5): quoting, approval/revision, crew scheduling,
fulfillment, cancellation."""

from datetime import timedelta

import db
import serializers
from clock import clock
from constants import ORDER_NONTERMINAL_STATUSES, SERVICE_CATEGORIES, SERVICE_WINDOW_MARGIN_HOURS
from errors import ApiError
from middleware import endpoint
from routes.common import list_response, one
from services import invoices as invoice_service
from services.intervals import overlap
from validate import (
    get_crew,
    get_event_masked,
    get_order_masked,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

READ_ROLES = ["ServiceCoordinator", "Scheduler", "OrgRequester"]


@endpoint("POST", "/campus/service-orders", roles=["OrgRequester"], code=201)
def create_order(ctx):
    body = ctx.body
    event_id = req_str(body, "event_id")
    event = get_event_masked(ctx, event_id)  # body FK + ownership masking (rung 3)
    category = req_enum(body, "category", SERVICE_CATEGORIES)
    quantity = req_int(body, "quantity")
    if quantity < 1:
        raise ApiError("ERR_INVALID_REQUEST", "quantity must be at least 1.")
    start_raw, start_dt = req_dt(body, "service_start_at")
    end_raw, end_dt = req_dt(body, "service_end_at")
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_TIME_RANGE", "service_end_at must be later than service_start_at.")
    margin = timedelta(hours=SERVICE_WINDOW_MARGIN_HOURS)
    if start_dt < event["_start"] - margin or end_dt > event["_end"] + margin:
        raise ApiError(
            "ERR_SERVICE_WINDOW_OUT_OF_RANGE",
            "The service window must lie within [event.start_at - 2h, event.end_at + 2h].",
        )
    if event["status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Service orders attach only to APPROVED or CONFIRMED events.",
        )
    row = db.new_row(
        db.service_orders,
        event_id=event["id"],
        category=category,
        quantity=quantity,
        unit_cost_cents=None,
        quoted_total_cents=None,
        service_start_at=start_raw,
        service_end_at=end_raw,
        crew_id=None,
        status="REQUESTED",
        fee_waived=False,
        revision_note=None,
        _service_start=start_dt,
        _service_end=end_dt,
    )
    return one(serializers.service_order(row), status=201)


@endpoint("GET", "/campus/service-orders/{id}", roles=READ_ROLES, code=200)
def get_order_detail(ctx):
    return one(serializers.service_order(get_order_masked(ctx, ctx.id)))


@endpoint("GET", "/campus/service-orders", roles=READ_ROLES, code=200)
def list_orders(ctx):
    rows = db.all_of(db.service_orders)
    if ctx.is_org_requester:
        rows = [
            r
            for r in rows
            if (db.event_reservations.get(r.get("event_id")) or {}).get("requester_org_id") == ctx.user_id
        ]
    return list_response(
        rows,
        ctx.args,
        serializers.service_order,
        mapping={
            "event_id": lambda r: r.get("event_id"),
            "crew_id": lambda r: r.get("crew_id"),
            "category": lambda r: r.get("category"),
            "status": lambda r: r.get("status"),
        },
    )


@endpoint("POST", "/campus/service-orders/{id}/quote", roles=["ServiceCoordinator"], code=200)
def quote_order(ctx):
    order = get_order_masked(ctx, ctx.id)
    unit_cost = req_int(ctx.body, "unit_cost_cents")
    if unit_cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must be non-negative.")
    if order["status"] not in ("REQUESTED", "NEEDS_REVISION"):
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED or NEEDS_REVISION order can be quoted.")
    event = db.event_reservations.get(order["event_id"])
    if event is None or event["status"] not in ("APPROVED", "CONFIRMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "The parent event must be APPROVED or CONFIRMED.",
        )
    order["unit_cost_cents"] = unit_cost
    order["quoted_total_cents"] = order["quantity"] * unit_cost
    order["revision_note"] = None
    order["status"] = "QUOTED"
    db.touch(order)
    invoice_service.recompute_provisional(event)
    return one(serializers.service_order(order))


@endpoint("POST", "/campus/service-orders/{id}/approve", roles=["OrgRequester"], code=200)
def approve_order(ctx):
    order = get_order_masked(ctx, ctx.id)  # ownership masked as 404
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUOTED order can be approved.")
    order["status"] = "APPROVED"
    db.touch(order)
    event = db.event_reservations.get(order["event_id"])
    if event is not None:
        invoice_service.recompute_provisional(event)
    return one(serializers.service_order(order))


@endpoint("POST", "/campus/service-orders/{id}/request-revision", roles=["OrgRequester"], code=200)
def request_revision(ctx):
    order = get_order_masked(ctx, ctx.id)  # ownership masked as 404
    note = req_str(ctx.body, "note")
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUOTED order can be sent back for revision.")
    order["status"] = "NEEDS_REVISION"
    order["revision_note"] = note
    db.touch(order)
    # While NEEDS_REVISION the order is excluded from the provisional service
    # charge.
    event = db.event_reservations.get(order["event_id"])
    if event is not None:
        invoice_service.recompute_provisional(event)
    return one(serializers.service_order(order))


@endpoint("POST", "/campus/service-orders/{id}/schedule", roles=["ServiceCoordinator"], code=200)
def schedule_order(ctx):
    order = get_order_masked(ctx, ctx.id)
    crew_id = req_str(ctx.body, "crew_id")
    crew = get_crew(crew_id)  # body FK existence (rung 3)
    if order["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED order can be scheduled.")
    # The three crew checks follow in order: category, shift coverage,
    # capacity.
    if crew["category"] != order["category"]:
        raise ApiError(
            "ERR_CREW_CATEGORY_MISMATCH",
            "The crew's category differs from the order's category.",
        )
    shift_start = crew["_shift_start_minutes"]
    shift_end = crew["_shift_end_minutes"]
    service_start_tod = order["_service_start"].hour * 60 + order["_service_start"].minute
    service_end_tod = order["_service_end"].hour * 60 + order["_service_end"].minute
    if not (shift_start <= service_start_tod and service_end_tod <= shift_end):
        raise ApiError(
            "ERR_CREW_SHIFT_MISMATCH",
            "The crew's shift does not cover the full service window.",
        )
    load = 0
    for other in db.service_orders.values():
        if other["id"] == order["id"]:
            continue
        if other.get("crew_id") != crew["id"] or other.get("status") != "SCHEDULED":
            continue
        # Half-open overlap: a window ending exactly when another begins is
        # NOT an overlap.
        if overlap(
            other["_service_start"], other["_service_end"], order["_service_start"], order["_service_end"]
        ):
            load += 1
    if load >= crew["concurrent_capacity"]:
        raise ApiError(
            "ERR_CREW_CAPACITY_EXCEEDED",
            "The crew's concurrent capacity would be exceeded.",
        )
    order["crew_id"] = crew["id"]
    order["status"] = "SCHEDULED"
    db.touch(order)
    return one(serializers.service_order(order))


@endpoint("POST", "/campus/service-orders/{id}/fulfill", roles=["ServiceCoordinator"], code=200)
def fulfill_order(ctx):
    order = get_order_masked(ctx, ctx.id)
    if order["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED order can be fulfilled.")
    if clock.now < order["_service_end"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The order can be fulfilled only once its service window has ended.",
        )
    order["status"] = "FULFILLED"
    db.touch(order)
    return one(serializers.service_order(order))


@endpoint("POST", "/campus/service-orders/{id}/cancel", roles=["ServiceCoordinator", "OrgRequester"], code=200)
def cancel_order(ctx):
    order = get_order_masked(ctx, ctx.id)  # OrgRequester ownership masked as 404
    if order["status"] not in ORDER_NONTERMINAL_STATUSES:
        raise ApiError("ERR_INVALID_STATE", "The order is already in a terminal state.")
    # A direct (requester- or coordinator-initiated) cancel is never a system
    # cascade: fee_waived is false.
    order["status"] = "CANCELLED"
    order["fee_waived"] = False
    db.touch(order)
    event = db.event_reservations.get(order["event_id"])
    if event is not None:
        invoice_service.recompute_provisional(event)
    return one(serializers.service_order(order))
