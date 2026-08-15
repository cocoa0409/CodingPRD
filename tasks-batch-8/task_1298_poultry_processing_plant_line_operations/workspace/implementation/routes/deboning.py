"""Deboning batches: schedule, lifecycle, completion cascade."""

from decimal import Decimal
from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LINE_TYPE_MISMATCH,
    ERR_ORDER_WINDOW_CLOSED,
    ERR_LABOR_BUDGET_EXCEEDED,
    ERR_SHIFT_NOT_RUNNING,
    ERR_SHIFT_TERMINAL,
    ERR_LOT_NOT_CHILLED,
    ERR_BATCH_NOT_ADVANCEABLE,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_int,
    check_number,
    check_string,
    parse_pagination,
)
from response import success_object, success_list
from services.core import (
    new_entity,
    _touch,
    lazy_lot,
    recompute_shift_labor,
    round2,
    TRIM_ALLOWANCE_PCT,
    POUNDS_PER_LABOR_HOUR,
)
from services.serializers import serialize_batch

bp = Blueprint("deboning", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)


def recompute_order_fill(order):
    """filled_lb = sum of net_weight_lb over COMPLETED batches; allocation_status."""
    filled = Decimal("0")
    for b in db.deboning_batches.values():
        if b["order_id"] == order["id"] and b["status"] == "COMPLETED":
            filled += Decimal(str(b["net_weight_lb"]))
    order["filled_lb"] = float(filled)
    pounds = Decimal(str(order["pounds_ordered"]))
    if filled == 0:
        order["allocation_status"] = "UNALLOCATED"
    elif filled < pounds:
        order["allocation_status"] = "PARTIALLY_ALLOCATED"
    else:
        order["allocation_status"] = "ALLOCATED"


@bp.route("/poultry/deboning-batches", methods=["POST"])
def create_batch():
    require_roles("ShiftSupervisor")
    body = get_json_body()
    check_no_unknown(
        body,
        {"order_id", "flock_lot_id", "shift_id", "line_id", "crew_count", "input_weight_lb"},
    )
    check_required(
        body,
        {"order_id", "flock_lot_id", "shift_id", "line_id", "crew_count", "input_weight_lb"},
    )
    check_string(body["order_id"], "order_id")
    check_string(body["flock_lot_id"], "flock_lot_id")
    check_string(body["shift_id"], "shift_id")
    check_string(body["line_id"], "line_id")
    check_int(body["crew_count"], "crew_count", min_value=1)
    check_number(body["input_weight_lb"], "input_weight_lb", min_value=0, exclusive_min=True)

    # Existence left-to-right
    order = db.orders.get(body["order_id"])
    if not order:
        raise ApiError(ERR_NOT_FOUND, "Order not found", 404)
    lot = db.flock_lots.get(body["flock_lot_id"])
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)
    shift = db.shifts.get(body["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    line = db.lines.get(body["line_id"])
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Line not found", 404)

    # Lazy lot chill evaluation on batch creation
    lazy_lot(lot)

    if shift["status"] == "CLOSED":
        raise ApiError(ERR_SHIFT_TERMINAL, "Mutation attempted on a CLOSED shift", 409)

    if line["line_type"] != "DEBONING":
        raise ApiError(ERR_LINE_TYPE_MISMATCH, "DeboningBatch requires a DEBONING line", 422)

    # Temporal gate: due_at must be in the future of the logical clock
    if db.clock_now() >= order["due_at"]:
        raise ApiError(
            ERR_ORDER_WINDOW_CLOSED,
            "Batch create attempted after the order's due_at",
            409,
        )

    # Fiscal gate LAST: estimated labor must fit remaining budget
    estimated = round2(Decimal(str(body["input_weight_lb"])) / POUNDS_PER_LABOR_HOUR)
    recompute_shift_labor(shift)
    if Decimal(str(estimated)) > Decimal(str(shift["labor_hours_remaining"])):
        raise ApiError(
            ERR_LABOR_BUDGET_EXCEEDED,
            "Batch estimated labor exceeds the shift's labor_hours_remaining",
            402,
        )

    batch = new_entity()
    batch.update({
        "order_id": order["id"],
        "flock_lot_id": lot["id"],
        "shift_id": shift["id"],
        "line_id": line["id"],
        "crew_count": body["crew_count"],
        "input_weight_lb": body["input_weight_lb"],
        "estimated_labor_hours": estimated,
        "actual_output_weight_lb": None,
        "actual_labor_hours": None,
        "net_weight_lb": None,
        "status": "SCHEDULED",
    })
    db.deboning_batches[batch["id"]] = batch

    # Debit estimate from the shift's remaining labor
    recompute_shift_labor(shift)
    _touch(shift)

    return success_object(serialize_batch(batch), 201)


@bp.route("/poultry/deboning-batches", methods=["GET"])
def list_batches():
    require_roles(*ALL_ROLES)
    items = list(db.deboning_batches.values())
    order_id = request.args.get("order_id")
    flock_lot_id = request.args.get("flock_lot_id")
    shift_id = request.args.get("shift_id")
    line_id = request.args.get("line_id")
    if order_id is not None:
        items = [b for b in items if b["order_id"] == order_id]
    if flock_lot_id is not None:
        items = [b for b in items if b["flock_lot_id"] == flock_lot_id]
    if shift_id is not None:
        items = [b for b in items if b["shift_id"] == shift_id]
    if line_id is not None:
        items = [b for b in items if b["line_id"] == line_id]
    items.sort(key=lambda b: b["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_batch(b) for b in page], limit, offset, len(items))


@bp.route("/poultry/deboning-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    require_roles(*ALL_ROLES)
    batch = db.deboning_batches.get(batch_id)
    if not batch:
        raise ApiError(ERR_NOT_FOUND, "Deboning batch not found", 404)
    return success_object(serialize_batch(batch))


@bp.route("/poultry/deboning-batches/<batch_id>/advance", methods=["POST"])
def advance_batch(batch_id):
    user_id, role = require_roles("LineOperator")
    batch = db.deboning_batches.get(batch_id)
    if not batch:
        raise ApiError(ERR_NOT_FOUND, "Deboning batch not found", 404)
    body = get_json_body()
    check_no_unknown(
        body, {"to_status", "actual_output_weight_lb", "actual_labor_hours"}
    )
    check_required(body, ["to_status"])
    check_enum(
        body["to_status"], ("IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED"), "to_status"
    )
    to_status = body["to_status"]

    shift = db.shifts.get(batch["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    if shift["status"] == "CLOSED":
        raise ApiError(ERR_SHIFT_TERMINAL, "Mutation attempted on a CLOSED shift", 409)

    if to_status == "IN_PROGRESS":
        if batch["status"] == "SCHEDULED":
            # Start: shift RUNNING + lot CHILLED/SETTLED/REOPENED
            if shift["status"] != "RUNNING":
                raise ApiError(
                    ERR_SHIFT_NOT_RUNNING,
                    "Batch start requires the enclosing shift in RUNNING",
                    409,
                )
            lot = db.flock_lots.get(batch["flock_lot_id"])
            if not lot:
                raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)
            lazy_lot(lot)
            if lot["status"] not in ("CHILLED", "SETTLED", "REOPENED"):
                raise ApiError(
                    ERR_LOT_NOT_CHILLED,
                    "Batch start attempted before the source lot reached CHILLED",
                    409,
                )
            batch["status"] = "IN_PROGRESS"
            _touch(batch)
            # Bubble: first batch into IN_PROGRESS moves order PENDING -> IN_PRODUCTION
            order = db.orders.get(batch["order_id"])
            if order and order["fulfillment_status"] == "PENDING":
                order["fulfillment_status"] = "IN_PRODUCTION"
                _touch(order)
        elif batch["status"] == "ON_HOLD":
            # Resume requires shift RUNNING
            if shift["status"] != "RUNNING":
                raise ApiError(
                    ERR_SHIFT_NOT_RUNNING,
                    "Batch resume requires the enclosing shift in RUNNING",
                    409,
                )
            batch["status"] = "IN_PROGRESS"
            _touch(batch)
        else:
            raise ApiError(
                ERR_BATCH_NOT_ADVANCEABLE,
                "IN_PROGRESS not reachable from current batch state",
                409,
            )
    elif to_status == "ON_HOLD":
        if batch["status"] != "IN_PROGRESS":
            raise ApiError(
                ERR_BATCH_NOT_ADVANCEABLE, "ON_HOLD permitted only from IN_PROGRESS", 409
            )
        batch["status"] = "ON_HOLD"
        _touch(batch)
    elif to_status == "CANCELLED":
        if batch["status"] != "SCHEDULED":
            raise ApiError(
                ERR_BATCH_NOT_ADVANCEABLE, "CANCELLED permitted only from SCHEDULED", 409
            )
        batch["status"] = "CANCELLED"
        _touch(batch)
        # Release estimate back to the shift (labor invariant)
        recompute_shift_labor(shift)
        _touch(shift)
    elif to_status == "COMPLETED":
        if batch["status"] != "IN_PROGRESS":
            raise ApiError(
                ERR_BATCH_NOT_ADVANCEABLE,
                "COMPLETED attempted from a state other than IN_PROGRESS",
                409,
            )
        if "actual_output_weight_lb" not in body or body["actual_output_weight_lb"] is None:
            raise ApiError(ERR_INVALID_REQUEST, "actual_output_weight_lb is required", 400)
        if "actual_labor_hours" not in body or body["actual_labor_hours"] is None:
            raise ApiError(ERR_INVALID_REQUEST, "actual_labor_hours is required", 400)
        check_number(
            body["actual_output_weight_lb"], "actual_output_weight_lb",
            min_value=0, exclusive_min=True,
        )
        check_number(
            body["actual_labor_hours"], "actual_labor_hours", min_value=0, exclusive_min=True
        )

        batch["actual_output_weight_lb"] = body["actual_output_weight_lb"]
        batch["actual_labor_hours"] = body["actual_labor_hours"]
        # Per-batch rounding pinned BEFORE order summation
        net = round2(
            Decimal(str(body["actual_output_weight_lb"])) * (Decimal(1) - TRIM_ALLOWANCE_PCT)
        )
        batch["net_weight_lb"] = net
        batch["status"] = "COMPLETED"
        _touch(batch)

        # Cascade 1: create the FinishedLot (OPEN / UNROUTED)
        lot = db.flock_lots.get(batch["flock_lot_id"])
        trace_code = f"{lot['lot_code']}/{shift['shift_code']}/{batch['id']}" if lot else f"/{shift['shift_code']}/{batch['id']}"
        flot = new_entity()
        flot.update({
            "deboning_batch_id": batch["id"],
            "order_id": batch["order_id"],
            "trace_code": trace_code,
            "net_weight_lb": net,
            "routing_status": "UNROUTED",
            "status": "OPEN",
            "locked_at": None,
            "shipped_at": None,
        })
        db.finished_lots[flot["id"]] = flot

        # Cascade 2: order fill recompute
        order = db.orders.get(batch["order_id"])
        if order:
            recompute_order_fill(order)
            _touch(order)

        # Cascade 3: labor ledger swap estimate -> actual
        recompute_shift_labor(shift)
        _touch(shift)

    return success_object(serialize_batch(batch))
