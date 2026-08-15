"""Storm activation endpoints (PRD 3.7): standby/call-out duty, conversion,
close with premium-pay computation, cancel. Crew status is derived on read."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_DUPLICATE_ACTIVE_STANDBY,
)
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from routes.work_packages import require_contract_active
from services.billing import compute_premium_pay
from services.core import new_record, touch
from util import num
from validate import (
    get_body, req_str, req_enum, req_date, req_num, require_path_resource,
    require_body_ref,
)

bp = Blueprint("storm", __name__)


@bp.post("/contracts/<contract_id>/storm-activations")
def create_storm_activation(contract_id):
    authorized(["UTILITY_DISPATCHER"])
    body = get_body()
    crew_id = req_str(body, "crew_id")
    kind = req_enum(body, "kind", {"STANDBY", "CALLOUT"})
    activation_date = req_date(body, "activation_date")
    contract = require_path_resource("contracts", contract_id)
    require_body_ref("crews", crew_id, "crew_id")
    require_contract_active(contract)
    # At most one ACTIVE storm activation per crew.
    for sa in db["storm_activations"].values():
        if sa["crew_id"] == crew_id and sa["status"] == "ACTIVE":
            raise_error(ERR_DUPLICATE_ACTIVE_STANDBY,
                        "crew already has an ACTIVE storm activation")
    rec = new_record("storm_activations", {
        "contract_id": contract["id"],
        "crew_id": crew_id,
        "kind": kind,
        "activation_date": activation_date,
        "hours_standby": None,
        "hours_worked": None,
        "premium_pay": None,
        "converted": False,
        "status": "ACTIVE",
    })
    return success_object(serialize("storm_activations", rec), status=201)


def _load_active_activation(storm_activation_id):
    sa = require_path_resource("storm_activations", storm_activation_id)
    contract = require_path_resource("contracts", sa["contract_id"])
    require_contract_active(contract)
    if sa["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE,
                    f"storm activation is {sa['status']}, not ACTIVE")
    return sa


@bp.post("/storm-activations/<storm_activation_id>/convert")
def convert_storm_activation(storm_activation_id):
    authorized(["UTILITY_DISPATCHER"])
    get_body()
    sa = _load_active_activation(storm_activation_id)
    if sa["kind"] != "STANDBY":
        raise_error(ERR_INVALID_STATE,
                    "only a STANDBY activation can be converted to CALLOUT")
    sa["kind"] = "CALLOUT"
    sa["converted"] = True
    touch(sa)
    return success_object(serialize("storm_activations", sa))


@bp.post("/storm-activations/<storm_activation_id>/close")
def close_storm_activation(storm_activation_id):
    authorized(["UTILITY_DISPATCHER"])
    body = get_body()
    hours_standby = req_num(body, "hours_standby", non_negative=True)
    hours_worked = req_num(body, "hours_worked", non_negative=True)
    sa = _load_active_activation(storm_activation_id)
    crew = require_path_resource("crews", sa["crew_id"])
    sa["hours_standby"] = hours_standby
    sa["hours_worked"] = hours_worked
    sa["premium_pay"] = num(compute_premium_pay(sa, crew))
    sa["status"] = "CLOSED"
    touch(sa)
    return success_object(serialize("storm_activations", sa))


@bp.post("/storm-activations/<storm_activation_id>/cancel")
def cancel_storm_activation(storm_activation_id):
    authorized(["UTILITY_DISPATCHER"])
    get_body()
    sa = _load_active_activation(storm_activation_id)
    sa["status"] = "CANCELLED"
    touch(sa)
    return success_object(serialize("storm_activations", sa))


@bp.get("/storm-activations")
def list_storm_activations():
    filters = {
        "contract_id": request.args.get("contract_id"),
        "crew_id": request.args.get("crew_id"),
        "status": request.args.get("status"),
    }
    return list_response("storm_activations", filters)


@bp.get("/storm-activations/<storm_activation_id>")
def get_storm_activation(storm_activation_id):
    return get_one("storm_activations", storm_activation_id)
