"""Machine registry endpoints."""
from flask import Blueprint

from db import store, new_id, touch, new_common
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services.audit import audit

bp = Blueprint("machines", __name__)

READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner", "MachineOperator"]


@bp.post("/fab/machines")
def create_machine():
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    body = parse_body({
        "name": ("string", True, None),
        "station": ("enum", True, ["LASER", "BRAKE", "WELD", "POWDER"]),
        "shift_minutes_per_day": ("integer", True, None),
    }, allow_empty=False)
    machine = {
        "id": new_id(),
        "name": body["name"],
        "station": body["station"],
        "shift_minutes_per_day": body["shift_minutes_per_day"],
        "status": "ACTIVE",
    }
    new_common(machine)
    store.machines[machine["id"]] = machine
    audit("Machine", machine["id"], "MACHINE_CREATED", role, uid,
          {"after": {"station": machine["station"], "status": "ACTIVE"}})
    return created(machine)


@bp.get("/fab/machines")
def list_machines():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    rows = list(store.machines.values())
    for f in ("station", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/machines/<machine_id>")
def get_machine(machine_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    return ok(require_path_entity(store.machines, machine_id))


@bp.get("/fab/machines/<machine_id>/routing-steps")
def machine_queue(machine_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager", "ProductionPlanner", "MachineOperator"])
    m = require_path_entity(store.machines, machine_id)
    rows = [st for st in store.routing_steps.values() if st.get("machine_id") == m["id"]]
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/fab/machines/<machine_id>/status")
def set_machine_status(machine_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    body = parse_body({"status": ("enum", True, ["ACTIVE", "DOWN"])}, allow_empty=False)
    m = require_path_entity(store.machines, machine_id)
    prev = m["status"]
    m["status"] = body["status"]
    touch(m)
    audit("Machine", m["id"], "MACHINE_STATUS_CHANGED", role, uid,
          {"before": {"status": prev}, "after": {"status": body["status"]}})
    return ok(m)
