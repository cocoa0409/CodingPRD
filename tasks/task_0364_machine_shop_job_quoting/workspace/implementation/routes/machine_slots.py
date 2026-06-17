"""MachineSlot routes (PRD §3.4)."""
from flask import Blueprint, request

from db import db, lock, base_fields, touch
from errors import err
from middleware import require_roles, require_auth
from helpers import (
    get_body, require_fields, validate_enum, as_int, as_str,
    paginate, serialize, serialize_list,
)
from response import success, list_response
import services as svc

bp = Blueprint("machine_slots", __name__)

MACHINE_CLASSES = {"MILL_3AX", "MILL_5AX", "LATHE"}


def get_slot_or_404(slot_id):
    slot = db.machine_slots.get(slot_id)
    if slot is None:
        raise err("ERR_NOT_FOUND", "MachineSlot not found")
    return slot


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: a starts before b ends and b starts
    before a ends. Abutting intervals do not conflict."""
    return a_start < b_end and b_start < a_end


@bp.route("/machine-slots", methods=["POST"])
def create_machine_slot():
    require_roles("Scheduler")
    body = get_body()
    require_fields(body, "machine_class", "machine_code", "routing_op_id",
                   "start_min", "end_min")
    machine_class = body["machine_class"]
    validate_enum(machine_class, MACHINE_CLASSES, "machine_class")
    machine_code = as_str(body, "machine_code")
    routing_op_id = as_str(body, "routing_op_id")
    start_min = as_int(body, "start_min")
    end_min = as_int(body, "end_min")
    if end_min <= start_min:
        raise err("ERR_INVALID_REQUEST", "end_min must be strictly greater than start_min")
    with lock():
        # existence: routing_op_id (body FK)
        op = db.routing_ops.get(routing_op_id)
        if op is None:
            raise err("ERR_NOT_FOUND", "RoutingOp not found")
        # temporal conflict on same machine_code among BOOKED slots
        for slot in db.machine_slots.values():
            if slot["status"] == "BOOKED" and slot["machine_code"] == machine_code:
                if _overlaps(start_min, end_min, slot["start_min"], slot["end_min"]):
                    raise err("ERR_SLOT_CONFLICT", "Slot overlaps an existing booked slot")
        rec = base_fields()
        rec.update({
            "machine_class": machine_class,
            "machine_code": machine_code,
            "routing_op_id": routing_op_id,
            "start_min": start_min,
            "end_min": end_min,
            "status": "BOOKED",
        })
        db.machine_slots[rec["id"]] = rec

        # scheduling side effects: drive op PLANNED -> SCHEDULED iff
        # owning quote APPROVED and the WO for that quote is RELEASED/IN_PROCESS
        quote = db.quotes.get(op["quote_id"])
        wos = svc.work_orders_for_quote(op["quote_id"])
        eligible_wos = [w for w in wos if w["status"] in ("RELEASED", "IN_PROCESS")]
        if (op["status"] == "PLANNED" and quote is not None
                and quote["status"] == "APPROVED" and eligible_wos):
            op["status"] = "SCHEDULED"
            touch(op)
            # bubble-up: first scheduled op of the WO's quote -> WO IN_PROCESS
            for w in eligible_wos:
                svc.maybe_bubble_wo_released_to_in_process(w)

        return success(serialize(rec), status=201)


@bp.route("/machine-slots/<slot_id>", methods=["GET"])
def get_machine_slot(slot_id):
    require_auth()
    with lock():
        return success(serialize(get_slot_or_404(slot_id)))


@bp.route("/machine-slots", methods=["GET"])
def list_machine_slots():
    require_auth()
    routing_op_id = request.args.get("routing_op_id")
    machine_code = request.args.get("machine_code")
    status = request.args.get("status")
    with lock():
        items = list(db.machine_slots.values())
        if routing_op_id:
            items = [s for s in items if s["routing_op_id"] == routing_op_id]
        if machine_code:
            items = [s for s in items if s["machine_code"] == machine_code]
        if status:
            items = [s for s in items if s["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/machine-slots/<slot_id>/release", methods=["POST"])
def release_machine_slot(slot_id):
    require_roles("Scheduler")
    with lock():
        slot = get_slot_or_404(slot_id)
        if slot["status"] != "BOOKED":
            raise err("ERR_INVALID_STATE", "MachineSlot must be BOOKED to release")
        slot["status"] = "RELEASED"
        touch(slot)
        # revert referenced RoutingOp SCHEDULED -> PLANNED
        op = db.routing_ops.get(slot["routing_op_id"])
        if op is not None and op["status"] == "SCHEDULED":
            op["status"] = "PLANNED"
            touch(op)
        return success(serialize(slot))
