"""LockerMachine + Compartment routes."""

from flask import Blueprint, g, request

from db import DB, LOCK
from middleware import require_roles
from response import success_object, success_array, parse_pagination
from services.audit import append_audit
from services.compartment_ops import in_service, out_of_service
from services.machine import (
    create_compartment,
    create_machine,
    force_offline,
    get_compartment,
    get_machine,
    heartbeat,
    list_compartments,
    list_machines,
    serialize_compartment,
    serialize_machine,
)


bp = Blueprint("machines", __name__)


@bp.route("/locker-machines", methods=["POST"])
@require_roles("OperationsAdmin")
def post_machine():
    with LOCK:
        m = create_machine(request.get_json(silent=True) or {})
        return success_object(serialize_machine(m), 201)


@bp.route("/locker-machines", methods=["GET"])
@require_roles("OperationsAdmin", "Courier", "Recipient", "Any")
def get_machines():
    with LOCK:
        limit, offset = parse_pagination(request.args)
        all_records = list_machines(request.args)
        sliced = all_records[offset: offset + limit]
        return success_array(
            [serialize_machine(m) for m in sliced],
            limit=limit, offset=offset, total_count=len(all_records),
        )


@bp.route("/locker-machines/<machine_id>", methods=["GET"])
@require_roles("OperationsAdmin", "Courier", "Recipient", "Any")
def get_one_machine(machine_id):
    with LOCK:
        m = get_machine(machine_id)
        return success_object(serialize_machine(m))


@bp.route("/locker-machines/<machine_id>/heartbeat", methods=["POST"])
@require_roles("OperationsAdmin")
def post_heartbeat(machine_id):
    with LOCK:
        m = heartbeat(machine_id, request.get_json(silent=True) or {})
        return success_object(serialize_machine(m))


@bp.route("/locker-machines/<machine_id>/offline", methods=["POST"])
@require_roles("OperationsAdmin")
def post_offline(machine_id):
    with LOCK:
        m = force_offline(machine_id, request.get_json(silent=True) or {})
        return success_object(serialize_machine(m))


@bp.route("/locker-machines/<machine_id>/audit-logs", methods=["GET"])
@require_roles("OperationsAdmin")
def get_audit_logs(machine_id):
    with LOCK:
        get_machine(machine_id)
        limit, offset = parse_pagination(request.args)
        action = request.args.get("action")
        # scope to this machine: subject is the machine itself OR a compartment under this machine
        # OR a parcel whose locker_machine_id == machine_id.
        machine_compartments = {
            c["id"] for c in DB.compartments.values()
            if c["locker_machine_id"] == machine_id
        }
        machine_parcels = {
            p["id"] for p in DB.parcels.values()
            if p.get("locker_machine_id") == machine_id
        }

        def in_scope(log):
            if log.get("subject_entity") == "LockerMachine" and log.get("subject_id") == machine_id:
                return True
            if log.get("subject_entity") == "Compartment" and log.get("subject_id") in machine_compartments:
                return True
            if log.get("subject_entity") == "Parcel" and log.get("subject_id") in machine_parcels:
                return True
            return False

        scoped = [log for log in DB.audit_logs if in_scope(log)]
        if action:
            scoped = [log for log in scoped if log.get("action") == action]
        scoped.sort(key=lambda r: (r.get("created_at") or "", r["id"]))
        sliced = scoped[offset: offset + limit]
        return success_array(sliced, limit=limit, offset=offset, total_count=len(scoped))


# --- Compartments ----------------------------------------------------------


@bp.route("/locker-machines/<machine_id>/compartments", methods=["POST"])
@require_roles("OperationsAdmin")
def post_compartment(machine_id):
    with LOCK:
        c = create_compartment(machine_id, request.get_json(silent=True) or {})
        return success_object(serialize_compartment(c), 201)


@bp.route("/locker-machines/<machine_id>/compartments", methods=["GET"])
@require_roles("OperationsAdmin", "Courier", "Recipient", "Any")
def get_compartments(machine_id):
    with LOCK:
        limit, offset = parse_pagination(request.args)
        all_records = list_compartments(machine_id, request.args)
        sliced = all_records[offset: offset + limit]
        return success_array(
            [serialize_compartment(c) for c in sliced],
            limit=limit, offset=offset, total_count=len(all_records),
        )


@bp.route("/locker-machines/<machine_id>/compartments/<compartment_id>", methods=["GET"])
@require_roles("OperationsAdmin", "Courier", "Recipient", "Any")
def get_one_compartment(machine_id, compartment_id):
    with LOCK:
        c = get_compartment(machine_id, compartment_id)
        return success_object(serialize_compartment(c))


@bp.route(
    "/locker-machines/<machine_id>/compartments/<compartment_id>/out-of-service",
    methods=["POST"],
)
@require_roles("OperationsAdmin")
def post_out_of_service(machine_id, compartment_id):
    with LOCK:
        c = out_of_service(machine_id, compartment_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_compartment(c))


@bp.route(
    "/locker-machines/<machine_id>/compartments/<compartment_id>/in-service",
    methods=["POST"],
)
@require_roles("OperationsAdmin")
def post_in_service(machine_id, compartment_id):
    with LOCK:
        c = in_service(machine_id, compartment_id, request.get_json(silent=True) or {}, g.user_id)
        return success_object(serialize_compartment(c))
