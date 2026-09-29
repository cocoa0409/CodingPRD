"""Secondary operations queued against a production lot (PRD 3.5)."""

from flask import Blueprint, g

import enums
from db import db, new_record, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok, ok_list
from services.lookup import (
    guard_disposition,
    lot_secondary_ops,
    production_lot_or_404,
    required_ops_satisfied,
    secondary_op_or_404,
    spec_for_lot,
)
from validate import (
    field_enum,
    field_int,
    field_str,
    paginate,
    pagination,
    query_enum,
)

bp = Blueprint("secondary_ops", __name__)

QUEUE_STATES = ("HEADED", "HEAT_TREATED", "SECONDARY_IN_PROGRESS")


@bp.post("/production-lots/<lot_id>/secondary-operations")
@endpoint("ProcessEngineer")
def create_secondary_op(lot_id):
    body = g.body
    op_type = field_enum(body, "op_type", enums.SECONDARY_OP_TYPES)
    sequence_no = field_int(body, "sequence_no", minimum=1)
    machine_code = field_str(body, "machine_code", allow_empty=True)

    lot = production_lot_or_404(lot_id)

    existing = lot_secondary_ops(lot_id)
    if any(op["sequence_no"] == sequence_no for op in existing):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER")

    guard_disposition(lot)

    if lot["process_state"] not in QUEUE_STATES:
        raise ApiError("ERR_INVALID_LOT_STATE")

    spec = spec_for_lot(lot)
    if op_type == "THREAD_ROLL":
        if lot["heat_treat_completed"]:
            if spec["thread_timing"] != "AFTER_HEAT_TREAT":
                raise ApiError("ERR_THREAD_TIMING_VIOLATION")
        else:
            if spec["thread_timing"] != "BEFORE_HEAT_TREAT":
                raise ApiError("ERR_THREAD_TIMING_VIOLATION")

    if any(op["status"] == "PENDING" for op in existing):
        raise ApiError("ERR_OP_SEQUENCE_CONFLICT")
    if any(sequence_no <= op["sequence_no"] for op in existing):
        raise ApiError("ERR_OP_SEQUENCE_CONFLICT")

    op = new_record(
        {
            "production_lot_id": lot_id,
            "op_type": op_type,
            "sequence_no": sequence_no,
            "machine_code": machine_code,
            "pieces_in": lot["available_count"],
            "pieces_out": None,
            "scrap_pieces": None,
            "status": "PENDING",
            "performed_after_heat_treat": bool(lot["heat_treat_completed"]),
        }
    )
    db.secondary_operations[op["id"]] = op

    lot["process_state"] = "SECONDARY_IN_PROGRESS"
    touch(lot)
    return created(op)


@bp.get("/production-lots/<lot_id>/secondary-operations")
@endpoint(ANY_ROLE)
def list_secondary_ops(lot_id):
    limit, offset = pagination()
    status = query_enum("status", enums.SECONDARY_OP_STATUSES)
    production_lot_or_404(lot_id)

    records = lot_secondary_ops(lot_id)
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/secondary-operations/<op_id>/complete")
@endpoint("ProcessEngineer")
def complete_secondary_op(op_id):
    pieces_out = field_int(g.body, "pieces_out", minimum=0)

    op = secondary_op_or_404(op_id)
    lot = db.production_lots.get(op["production_lot_id"])
    if lot is None:
        raise ApiError("ERR_PRODUCTION_LOT_NOT_FOUND")

    guard_disposition(lot)

    if op["status"] != "PENDING":
        raise ApiError("ERR_INVALID_SECONDARY_OP_STATE")

    if pieces_out > int(op["pieces_in"]):
        raise ApiError("ERR_PIECE_COUNT_INVALID")

    scrap = int(op["pieces_in"]) - pieces_out
    op["status"] = "DONE"
    op["pieces_out"] = pieces_out
    op["scrap_pieces"] = scrap
    touch(op)

    lot["available_count"] = pieces_out
    lot["scrap_count"] = int(lot["scrap_count"]) + scrap

    spec = spec_for_lot(lot)
    if lot["process_state"] == "SECONDARY_IN_PROGRESS" and required_ops_satisfied(lot, spec):
        lot["process_state"] = "SECONDARY_DONE"
    touch(lot)
    return ok(op)
