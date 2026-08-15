"""FinishedRoll endpoints.

Put-up requires the parent dye lot to be APPROVED (ERR_REFERENTIAL_VIOLATION).
At creation: yardage_deviation_pct computed, is_second_quality inherited from
the parent dye lot's quality test grade.
"""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_referential_violation,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_finished_roll
from services.calculations import yardage_deviation_pct
from services.workflows import (
    latest_grade,
    maybe_settle_order_shipped,
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
    req_decimal,
    req_string,
    sort_and_paginate,
)

bp = Blueprint("finished_rolls", __name__)

ROLES = ("DyeHouseOperator", "QualityInspector", "CustomerServiceRep")


def _get_roll_or_404(rid):
    record = db.finished_rolls.get(rid)
    if record is None:
        raise err_not_found("Finished roll not found")
    return record


@bp.post("/mill/finished-rolls")
def create_finished_roll():
    require_roles("DyeHouseOperator")
    body = get_json_body()
    dye_lot_id = req_string(body, "dye_lot_id")
    put_up = req_decimal(body, "put_up_yards", min_value=0, min_exclusive=True)
    actual = req_decimal(body, "actual_yards", min_value=0, min_exclusive=True)

    dye_lot = db.dye_lots.get(dye_lot_id)
    if dye_lot is None:
        raise err_reference_not_found("dye_lot_id does not resolve to an existing dye lot")

    # Referential integrity (priority 9)
    if dye_lot["status"] != "APPROVED":
        raise err_referential_violation("Finished rolls may only be cut from an APPROVED dye lot")

    grade = latest_grade(dye_lot["id"])
    is_second = grade == "SECOND_QUALITY"

    # PRD §3.6: per-roll put_up_yards / actual_yards are stored raw — only
    # yardage aggregates round to 2dp (put-up totals round each roll first;
    # allocation totals sum raw actual_yards and round the aggregate).
    ts = now_iso()
    record = {
        "id": new_id(),
        "dye_lot_id": dye_lot["id"],
        "put_up_yards": put_up,
        "actual_yards": actual,
        "yardage_deviation_pct": yardage_deviation_pct(put_up, actual),
        "is_second_quality": is_second,
        "allocated_order_id": None,
        "status": "AVAILABLE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.finished_rolls[record["id"]] = record
    return success_object(serialize_finished_roll(record), 201)


@bp.get("/mill/finished-rolls")
def list_finished_rolls():
    require_roles(*ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.finished_rolls.values()),
        {
            "dye_lot_id": request.args.get("dye_lot_id"),
            "status": request.args.get("status"),
            "is_second_quality": request.args.get("is_second_quality"),
            "allocated_order_id": request.args.get("allocated_order_id"),
        },
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_finished_roll(r) for r in page], limit, offset, total)


@bp.get("/mill/finished-rolls/<rid>")
def get_finished_roll(rid):
    require_roles(*ROLES)
    return success_object(serialize_finished_roll(_get_roll_or_404(rid)))


@bp.post("/mill/finished-rolls/<rid>/ship")
def ship_roll(rid):
    require_roles("CustomerServiceRep")
    record = _get_roll_or_404(rid)
    if record["status"] != "ALLOCATED":
        raise err_invalid_state("Only an ALLOCATED roll can be shipped")
    record["status"] = "SHIPPED"
    touch(record)

    order = db.customer_orders.get(record.get("allocated_order_id"))
    if order is not None:
        maybe_settle_order_shipped(order)
        # Check whether the yarn lot has fully drained
        dye_lot = db.dye_lots.get(record["dye_lot_id"])
        if dye_lot is not None:
            yarn_lot = db.yarn_lots.get(dye_lot["yarn_lot_id"])
            if yarn_lot is not None:
                maybe_settle_yarn_lot_allocated(yarn_lot)

    return success_object(serialize_finished_roll(record))


@bp.post("/mill/finished-rolls/<rid>/release")
def release_roll(rid):
    require_roles("CustomerServiceRep")
    record = _get_roll_or_404(rid)
    if record["status"] != "ALLOCATED":
        raise err_invalid_state("Only an ALLOCATED roll can be released")
    order = db.customer_orders.get(record.get("allocated_order_id"))
    record["status"] = "AVAILABLE"
    record["allocated_order_id"] = None
    touch(record)

    if order is not None:
        recompute_order_allocated_yards(order)
        recompute_order_status(order)
        touch(order)

    return success_object(serialize_finished_roll(record))


@bp.post("/mill/finished-rolls/<rid>/close-out")
def close_out_roll(rid):
    require_roles("CustomerServiceRep")
    record = _get_roll_or_404(rid)
    if record["status"] != "AVAILABLE":
        raise err_invalid_state("Only an AVAILABLE roll can be routed to close-out")
    if not record.get("is_second_quality"):
        raise err_invalid_state("Only a second-quality roll can be routed to close-out")
    record["status"] = "CLOSE_OUT"
    touch(record)

    dye_lot = db.dye_lots.get(record["dye_lot_id"])
    if dye_lot is not None:
        yarn_lot = db.yarn_lots.get(dye_lot["yarn_lot_id"])
        if yarn_lot is not None:
            maybe_settle_yarn_lot_allocated(yarn_lot)

    return success_object(serialize_finished_roll(record))
