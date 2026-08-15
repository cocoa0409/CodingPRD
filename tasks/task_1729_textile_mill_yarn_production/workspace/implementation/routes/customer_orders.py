"""CustomerOrder endpoints.

Allocation guards (PRD §3.7, validation cascade §2.10):
  - OCC via expected_order_version -> ERR_STALE_VERSION (412)
  - roll must be AVAILABLE, first-quality, color-matched to the order
  - order must be OPEN or PARTIALLY_ALLOCATED
On success: roll AVAILABLE -> ALLOCATED, allocated_yards recomputed via the
sum-then-round variant, status auto-transitions, version + 1.

Cancel cascade: all ALLOCATED rolls -> AVAILABLE, allocated_yards zeroed.
"""

from decimal import Decimal

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_second_quality_not_allocatable,
    err_stale_version,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_customer_order
from services.workflows import (
    maybe_settle_yarn_lot_allocated,
    recompute_order_allocated_yards,
    recompute_order_status,
    rolls_of_order,
    touch,
)
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    opt_decimal,
    req_decimal,
    req_string,
    round2,
    sort_and_paginate,
)

bp = Blueprint("customer_orders", __name__)

ROLES = ("CustomerServiceRep", "MillPlanner")


def _get_order_or_404(oid):
    record = db.customer_orders.get(oid)
    if record is None:
        raise err_not_found("Customer order not found")
    return record


@bp.post("/mill/customer-orders")
def create_customer_order():
    require_roles("CustomerServiceRep")
    body = get_json_body()
    customer_code = req_string(body, "customer_code")
    color_code = req_string(body, "color_code")
    requested_yards = req_decimal(body, "requested_yards", min_value=0, min_exclusive=True)
    tolerance = opt_decimal(body, "yardage_tolerance_pct", min_value=0, max_value=10, default=Decimal("2.0"))

    ts = now_iso()
    record = {
        "id": new_id(),
        "customer_code": customer_code,
        "color_code": color_code,
        "requested_yards": round2(requested_yards),
        "allocated_yards": Decimal("0"),
        "yardage_tolerance_pct": round2(tolerance),
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.customer_orders[record["id"]] = record
    return success_object(serialize_customer_order(record), 201)


@bp.get("/mill/customer-orders")
def list_customer_orders():
    require_roles(*ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.customer_orders.values()),
        {"customer_code": request.args.get("customer_code"), "status": request.args.get("status")},
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_customer_order(r) for r in page], limit, offset, total)


@bp.get("/mill/customer-orders/<oid>")
def get_customer_order(oid):
    require_roles(*ROLES)
    return success_object(serialize_customer_order(_get_order_or_404(oid)))


@bp.post("/mill/customer-orders/<oid>/allocate")
def allocate_roll(oid):
    require_roles("CustomerServiceRep")
    order = _get_order_or_404(oid)
    body = get_json_body()
    roll_id = req_string(body, "roll_id")

    # OCC — expected_order_version is required (PRD §2.8)
    if "expected_order_version" not in body or body["expected_order_version"] is None:
        from errors import err_invalid_request
        raise err_invalid_request("Missing required field: expected_order_version")
    expected = body["expected_order_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        from errors import err_invalid_request
        raise err_invalid_request("expected_order_version must be an integer")
    if expected != order["version"]:
        raise err_stale_version("expected_order_version does not match the order's current version")

    # Reference existence (priority 4)
    roll = db.finished_rolls.get(roll_id)
    if roll is None:
        raise err_reference_not_found("roll_id does not resolve to an existing finished roll")

    # State legality (priority 5): order must be OPEN or PARTIALLY_ALLOCATED; roll AVAILABLE
    if order["status"] not in ("OPEN", "PARTIALLY_ALLOCATED"):
        raise err_invalid_state("Order must be OPEN or PARTIALLY_ALLOCATED to accept allocations")
    if roll["status"] != "AVAILABLE":
        raise err_invalid_state("Roll must be AVAILABLE to be allocated")

    # Color match guard
    dye_lot = db.dye_lots.get(roll["dye_lot_id"])
    band = db.shade_bands.get(dye_lot["shade_band_id"]) if dye_lot is not None else None
    if band is None or band["color_code"] != order["color_code"]:
        raise err_invalid_state("Roll's shade band color_code does not match the order's color_code")

    # Channel discipline (priority 11)
    if roll.get("is_second_quality"):
        raise err_second_quality_not_allocatable("Second-quality rolls must go to the close-out channel")

    roll["status"] = "ALLOCATED"
    roll["allocated_order_id"] = order["id"]
    touch(roll)

    recompute_order_allocated_yards(order)
    recompute_order_status(order)
    touch(order)

    # Yarn lot lifecycle settlement check
    if dye_lot is not None:
        yarn_lot = db.yarn_lots.get(dye_lot["yarn_lot_id"])
        if yarn_lot is not None:
            maybe_settle_yarn_lot_allocated(yarn_lot)

    return success_object(serialize_customer_order(order))


@bp.post("/mill/customer-orders/<oid>/cancel")
def cancel_order(oid):
    require_roles("CustomerServiceRep")
    order = _get_order_or_404(oid)
    if order["status"] not in ("OPEN", "PARTIALLY_ALLOCATED"):
        raise err_invalid_state("Only an OPEN or PARTIALLY_ALLOCATED order can be cancelled")

    # Release cascade: every ALLOCATED roll on this order returns to AVAILABLE
    for roll in rolls_of_order(order["id"]):
        if roll["status"] == "ALLOCATED":
            roll["status"] = "AVAILABLE"
            roll["allocated_order_id"] = None
            touch(roll)

    order["allocated_yards"] = Decimal("0")
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(serialize_customer_order(order))
