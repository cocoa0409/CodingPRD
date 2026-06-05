"""Routing + Operation endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response, array_response
from serialize import public, public_list

bp = Blueprint("routings", __name__)


@bp.route("/routings", methods=["POST"])
def create_routing():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "PlantAdmin"])
    body = get_json_body()

    product_id = V.as_string(V.require(body, "product_id"), "product_id")
    routing_code = V.as_string(V.require(body, "routing_code"), "routing_code")

    with db.LOCK:
        lookups.product(product_id)
        # routing_code unique per (product_id, routing_code)
        for r in db.routings.values():
            if r["product_id"] == product_id and r["routing_code"] == routing_code:
                raise errors.invalid_request("routing_code must be unique within the product.")
        rec = db.new_record()
        rec.update({
            "product_id": product_id,
            "routing_code": routing_code,
            "status": "DRAFT",
            "operation_count": 0,
        })
        db.routings[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/routings/<rid>", methods=["GET"])
def get_routing(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "PlantAdmin"])
    return object_response(public(lookups.routing(rid)))


@bp.route("/routings", methods=["GET"])
def list_routings():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    rows = list(db.routings.values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.route("/routings/<rid>/operations", methods=["POST"])
def add_operation(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "PlantAdmin"])
    body = get_json_body()

    with db.LOCK:
        routing = lookups.routing(rid)

        machine_id = V.as_string(V.require(body, "machine_id"), "machine_id")
        sequence_no = V.as_int(V.require(body, "sequence_no"), "sequence_no")
        cycle = V.as_number(V.require(body, "ideal_cycle_time_secs"), "ideal_cycle_time_secs")
        setup = 0
        if "setup_buffer_secs" in body and body["setup_buffer_secs"] is not None:
            setup = V.as_int(body["setup_buffer_secs"], "setup_buffer_secs")

        # existence of referenced machine
        lookups.machine(machine_id)

        # operations attached only while DRAFT
        if routing["status"] != "DRAFT":
            raise errors.invalid_state("Operations may only be attached to a DRAFT routing.")

        # ERR_DUPLICATE_SEQUENCE (priority 12): sequence unique within routing
        for op in db.operations.values():
            if op["routing_id"] == rid and op["sequence_no"] == sequence_no:
                raise errors.ApiError(errors.ERR_DUPLICATE_SEQUENCE,
                                      "sequence_no already used in this routing.", 409)

        # field range constraints
        if sequence_no <= 0:
            raise errors.invalid_request("sequence_no must be > 0.")
        if cycle <= 0:
            raise errors.invalid_request("ideal_cycle_time_secs must be > 0.")
        if setup < 0:
            raise errors.invalid_request("setup_buffer_secs must be >= 0.")

        rec = db.new_record()
        rec.update({
            "routing_id": rid,
            "machine_id": machine_id,
            "sequence_no": sequence_no,
            "ideal_cycle_time_secs": cycle,
            "setup_buffer_secs": setup,
        })
        db.operations[rec["id"]] = rec

        # recompute routing.operation_count -> mutation of routing
        routing["operation_count"] = sum(
            1 for o in db.operations.values() if o["routing_id"] == rid)
        db.touch(routing)

        return object_response(public(rec), 201)


@bp.route("/routings/<rid>/operations", methods=["GET"])
def list_routing_operations(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator", "PlantAdmin"])
    lookups.routing(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [o for o in db.operations.values() if o["routing_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.route("/routings/<rid>/release", methods=["POST"])
def release_routing(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "PlantAdmin"])
    with db.LOCK:
        routing = lookups.routing(rid)
        if routing["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT routing may be released.")
        # preconditions: operation_count >= 1 and every operation references an
        # existing machine.
        ops = [o for o in db.operations.values() if o["routing_id"] == rid]
        if routing["operation_count"] < 1 or len(ops) < 1:
            raise errors.invalid_state("Routing must have at least one operation to release.")
        for op in ops:
            if op["machine_id"] not in db.machines:
                raise errors.not_found("Operation references a missing machine.")
        routing["status"] = "RELEASED"
        db.touch(routing)
        return object_response(public(routing))


@bp.route("/routings/<rid>/archive", methods=["POST"])
def archive_routing(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "PlantAdmin"])
    with db.LOCK:
        routing = lookups.routing(rid)
        if routing["status"] != "RELEASED":
            raise errors.invalid_state("Only a RELEASED routing may be archived.")
        # precondition: no WorkOrder in {RELEASED, IN_PROCESS} references this routing.
        for wo in db.work_orders.values():
            if wo["routing_id"] == rid and wo["status"] in ("RELEASED", "IN_PROCESS"):
                raise errors.invalid_state(
                    "Routing is referenced by an active work order.")
        routing["status"] = "ARCHIVED"
        db.touch(routing)
        return object_response(public(routing))
