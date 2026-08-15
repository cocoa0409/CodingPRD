"""Sortation batch endpoints (PRD section 3.5)."""
from flask import Blueprint, request

import db
from errors import err_door_kind_mismatch, err_invalid_state, err_terminal_closed
from middleware import require_roles
from response import success, success_list
from routes.common import (body_json, get_path, new_record, paginate,
                           resolve_fk, ser_batch, touch)

bp = Blueprint("batches", __name__)

_READ_ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor")


@bp.route("/ltl/sortation-batches", methods=["POST"])
@require_roles("DockSupervisor")
def create_batch():
    body = body_json()
    terminal = resolve_fk("terminals", body.get("terminal_id"), "terminal_id")
    door = resolve_fk("dock_doors", body.get("inbound_door_id"), "inbound_door_id")
    dest = resolve_fk("terminals", body.get("destination_terminal_id"), "destination_terminal_id")
    # Priority 10: door-kind agreement.
    if door["door_kind"] != "INBOUND":
        raise err_door_kind_mismatch("A sortation batch must strip at an INBOUND door")
    # Priority 16: closed-terminal guard.
    if terminal["status"] == "CLOSED":
        raise err_terminal_closed("Cannot open a sortation batch at a CLOSED terminal")
    rec = new_record({
        "terminal_id": terminal["id"], "inbound_door_id": door["id"],
        "destination_terminal_id": dest["id"], "status": "OPEN",
    })
    db.store["sortation_batches"][rec["id"]] = rec
    return success(ser_batch(rec), 201)


@bp.route("/ltl/sortation-batches", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_batches():
    items = list(db.store["sortation_batches"].values())
    for param in ("terminal_id", "inbound_door_id", "destination_terminal_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [b for b in items if b.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_batch(b) for b in page], total, limit, offset)


@bp.route("/ltl/sortation-batches/<batchId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_batch(batchId):
    return success(ser_batch(get_path("sortation_batches", batchId)))


@bp.route("/ltl/sortation-batches/<batchId>/close", methods=["POST"])
@require_roles("DockSupervisor")
def close_batch(batchId):
    batch = get_path("sortation_batches", batchId)
    if batch["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN batch can be closed")
    batch["status"] = "CLOSED"
    touch(batch)
    return success(ser_batch(batch))


@bp.route("/ltl/sortation-batches/<batchId>/disposition", methods=["POST"])
@require_roles("DockSupervisor")
def disposition_batch(batchId):
    batch = get_path("sortation_batches", batchId)
    if batch["status"] != "CLOSED":
        raise err_invalid_state("Only a CLOSED batch can be dispositioned")
    batch["status"] = "DISPOSITIONED"
    touch(batch)
    return success(ser_batch(batch))
