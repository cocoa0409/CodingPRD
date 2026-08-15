"""Machine asset endpoints (PRD 3.2). Cyclic ACTIVE <-> QUARANTINED."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE_TRANSITION
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.core import new_record, serialize, touch
from validate import get_body, req_enum, req_int, req_str, require_path_resource

bp = Blueprint("machines", __name__)

GUARD_TYPES = {"FIXED", "ADJUSTABLE", "NONE"}


@bp.post("/api/machines")
def create_machine():
    authorized(["AccountManager"])
    body = get_body()
    rec = new_record("machines", {
        "customer_ref": req_str(body, "customer_ref"),
        "asset_tag": req_str(body, "asset_tag"),
        "machine_type": req_str(body, "machine_type"),
        "spindle_max_rpm": req_int(body, "spindle_max_rpm", min_value=1),
        "guard_type": req_enum(body, "guard_type", GUARD_TYPES),
        "status": "ACTIVE",
        "consumption_flag": "NORMAL",
    })
    return success_object(serialize(rec), status=201)


@bp.get("/api/machines/<mid>")
def get_machine(mid):
    return get_one("machines", mid, "machine")


@bp.post("/api/machines/<mid>/quarantine")
def quarantine_machine(mid):
    authorized(["EHSOfficer"])
    machine = require_path_resource("machines", mid, "machine")
    if machine["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only an ACTIVE machine can be quarantined")
    machine["status"] = "QUARANTINED"
    touch(machine)
    return success_object(serialize(machine))


@bp.post("/api/machines/<mid>/reinstate")
def reinstate_machine(mid):
    authorized(["EHSOfficer"])
    machine = require_path_resource("machines", mid, "machine")
    if machine["status"] != "QUARANTINED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only a QUARANTINED machine can be reinstated")
    machine["status"] = "ACTIVE"
    touch(machine)
    return success_object(serialize(machine))
