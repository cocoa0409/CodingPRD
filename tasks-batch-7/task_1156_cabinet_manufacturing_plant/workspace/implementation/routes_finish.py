"""Finish room: batches, sheen lots, color QC, remix (PRD §3.4)."""
from flask import Blueprint, request

from auth import require_any_role, require_roles
from domain import (
    batch_assigned_door_count,
    live_lines,
    place_hold,
    reevaluate_order,
    release_hold,
)
from errors import api_error
from serializers import ser_finish_batch
from store import db, new_id, stamp, touch
from util import Body, D, paginate, respond_list, respond_object, sort_records

bp = Blueprint("finish", __name__)


def _get_batch(batch_id):
    batch = db.batches.get(batch_id)
    if batch is None:
        raise api_error("ERR_BATCH_NOT_FOUND", f"FinishBatch {batch_id} not found")
    return batch


@bp.post("/kcma/finish-batches")
def create_finish_batch():
    require_roles({"FinishSupervisor"})
    body = Body(request.get_json(silent=True))
    finish_id = body.req_str("finish_id")
    sheen_lot_no = body.req_str("sheen_lot_no")
    capacity_doors = body.req_int("capacity_doors", min_value=1)

    # priority 5: body FK exists
    finish = None
    if finish_id is not None:
        finish = db.finish_specs.get(finish_id)
        if finish is None:
            raise api_error("ERR_FINISH_NOT_FOUND", f"FinishSpec {finish_id} not found")
    # priority 8: finish must be active
    if finish is not None and not finish["active"]:
        raise api_error("ERR_FINISH_INACTIVE", f"FinishSpec {finish_id} is inactive")
    body.raise_field_errors()  # priority 14

    batch = {
        "id": new_id(),
        "finish_id": finish_id,
        "sheen_lot_no": sheen_lot_no,
        "capacity_doors": capacity_doors,
        "measured_delta_e": None,
        "remix_count": 0,
        "status": "MIXING",
    }
    stamp(batch)
    db.batches[batch["id"]] = batch
    return respond_object(ser_finish_batch(batch), 201)


@bp.get("/kcma/finish-batches")
def list_finish_batches():
    require_any_role()
    records = list(db.batches.values())
    finish_id = request.args.get("finish_id")
    if finish_id is not None:
        records = [b for b in records if b["finish_id"] == finish_id]
    status = request.args.get("status")
    if status is not None:
        records = [b for b in records if b["status"] == status]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_finish_batch(b) for b in page], total, limit, offset)


@bp.get("/kcma/finish-batches/<batchId>")
def get_finish_batch(batchId):
    require_any_role()
    return respond_object(ser_finish_batch(_get_batch(batchId)), 200)


@bp.post("/kcma/finish-batches/<batchId>/assign")
def assign_batch_line(batchId):
    require_roles({"FinishSupervisor"})
    batch = _get_batch(batchId)                                   # priority 4
    body = Body(request.get_json(silent=True))
    order_line_id = body.req_str("order_line_id")
    # priority 5: body FK exists
    line = None
    if order_line_id is not None:
        line = db.order_lines.get(order_line_id)
        if line is None:
            raise api_error("ERR_ORDER_LINE_NOT_FOUND", f"OrderLine {order_line_id} not found")
    # priority 6: batch in MIXING, then target line is a QUOTED unassigned DOOR line
    if batch["status"] != "MIXING":
        raise api_error("ERR_BATCH_NOT_MIXING", "Assign requires the batch in MIXING")
    if line is not None and (
        line["line_type"] != "DOOR"
        or line["status"] != "QUOTED"
        or line["finish_batch_id"] is not None
    ):
        raise api_error(
            "ERR_LINE_NOT_ASSIGNABLE",
            "Batch assign target must be a QUOTED, unassigned DOOR line",
        )
    # priority 10: compatibility in the pinned written order
    if line is not None:
        if line["finish_id"] != batch["finish_id"]:
            raise api_error("ERR_FINISH_MISMATCH", "Line finish does not match batch finish")
        if (
            line["required_sheen_lot_no"] is not None
            and line["required_sheen_lot_no"] != batch["sheen_lot_no"]
        ):
            raise api_error("ERR_SHEEN_LOT_MISMATCH", "Line sheen lot does not match batch lot")
        if batch_assigned_door_count(batch["id"]) + line["qty"] > batch["capacity_doors"]:
            raise api_error("ERR_BATCH_CAPACITY_EXCEEDED", "Batch door capacity exceeded")
    body.raise_field_errors()  # priority 14

    line["finish_batch_id"] = batch["id"]
    line["status"] = "IN_PROGRESS"  # QUOTED -> IN_PROGRESS
    touch(line)

    order = db.orders[line["order_id"]]
    # If this was the held order's last unassigned DOOR line, its PLACED
    # FINISH_QC holds release automatically (PRD §3.7).
    unassigned_doors = [
        l for l in live_lines(order)
        if l["line_type"] == "DOOR" and l["finish_batch_id"] is None
    ]
    if not unassigned_doors:
        for hold in list(db.holds.values()):
            if (
                hold["order_id"] == order["id"]
                and hold["reason"] == "FINISH_QC"
                and hold["status"] == "PLACED"
            ):
                release_hold(hold)
    reevaluate_order(order)
    return respond_object(ser_finish_batch(batch), 200)


@bp.post("/kcma/finish-batches/<batchId>/qc-record")
def record_batch_qc(batchId):
    require_roles({"FinishSupervisor"})
    batch = _get_batch(batchId)                                   # priority 4
    body = Body(request.get_json(silent=True))
    measured_delta_e = body.req_num("measured_delta_e")
    # priority 6: batch in MIXING
    if batch["status"] != "MIXING":
        raise api_error("ERR_BATCH_NOT_MIXING", "QC recording requires the batch in MIXING")
    body.raise_field_errors()  # priority 14

    finish = db.finish_specs[batch["finish_id"]]
    batch["measured_delta_e"] = measured_delta_e
    assigned = [
        l for l in db.order_lines.values()
        if l["finish_batch_id"] == batch["id"] and l["status"] != "CANCELLED"
    ]
    # batch_color_match: deviation exactly equal to tolerance passes (<=)
    if abs(D(measured_delta_e)) <= D(finish["delta_e_tolerance"]):
        batch["status"] = "RELEASED"
        touch(batch)
        affected_orders = []
        for line in assigned:
            line["status"] = "COMPLETED"  # IN_PROGRESS -> COMPLETED
            touch(line)
            if line["order_id"] not in affected_orders:
                affected_orders.append(line["order_id"])
        for order_id in affected_orders:
            reevaluate_order(db.orders[order_id])
    else:
        batch["status"] = "FAILED"
        touch(batch)
        # cascade hop 1: unassign every assigned door line
        affected_order_ids = []
        for line in assigned:
            line["finish_batch_id"] = None
            line["status"] = "QUOTED"  # IN_PROGRESS -> QUOTED fallback
            touch(line)
            if line["order_id"] not in affected_order_ids:
                affected_order_ids.append(line["order_id"])
        # cascade hop 2: FINISH_QC hold per distinct affected order
        for order_id in affected_order_ids:
            place_hold(order_id, "FINISH_QC")
        # hop 3: hold_status now ON_HOLD for those orders (computed on read),
        # gating IN_PRODUCTION / READY_TO_SHIP and route locking.
    return respond_object(ser_finish_batch(batch), 200)


@bp.post("/kcma/finish-batches/<batchId>/remix")
def remix_batch(batchId):
    require_roles({"FinishSupervisor"})
    batch = _get_batch(batchId)
    if batch["status"] != "FAILED":
        raise api_error("ERR_BATCH_NOT_REMIXABLE", "Remix requires the batch in FAILED")
    batch["measured_delta_e"] = None
    batch["remix_count"] += 1
    batch["status"] = "MIXING"
    touch(batch)
    return respond_object(ser_finish_batch(batch), 200)
