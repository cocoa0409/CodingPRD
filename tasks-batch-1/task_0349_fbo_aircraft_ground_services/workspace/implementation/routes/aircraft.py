"""Aircraft endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import get_json, require_string, require_int, require_enum, pagination_params, paginate
from services.derived import compute_weight_class

bp = Blueprint("aircraft", __name__)


def aircraft_view(ac):
    return {
        "id": ac["id"],
        "operator_id": ac["operator_id"],
        "tail_number": ac["tail_number"],
        "fuel_type": ac["fuel_type"],
        "mtow_lb": ac["mtow_lb"],
        "weight_class": ac["weight_class"],
        "created_at": ac["created_at"],
        "updated_at": ac["updated_at"],
        "version": ac["version"],
    }


@bp.route("/aircraft", methods=["POST"])
def create_aircraft():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    body = get_json()
    operator_id = require_string(body, "operator_id")
    tail_number = require_string(body, "tail_number")
    fuel_type = require_enum(body, "fuel_type", {"JET_A", "AVGAS"})
    mtow_lb = require_int(body, "mtow_lb", minimum=1)

    # Ownership (Operator role) before existence per §3.10.
    if role == "Operator" and user_id != operator_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may register only its own aircraft.")
    # Existence of FK.
    operator = db.operators.get(operator_id)
    if operator is None:
        raise err(errors.ERR_NOT_FOUND, "Operator not found.")
    # Uniqueness: tail_number unique within operator_id.
    for ac in db.aircraft.values():
        if ac["operator_id"] == operator_id and ac["tail_number"] == tail_number:
            raise err(errors.ERR_DUPLICATE_RESOURCE, "Duplicate tail_number for this operator.")

    ac = db.common_create()
    ac.update({
        "operator_id": operator_id,
        "tail_number": tail_number,
        "fuel_type": fuel_type,
        "mtow_lb": mtow_lb,
        "weight_class": compute_weight_class(mtow_lb),
    })
    db.aircraft[ac["id"]] = ac
    return success(aircraft_view(ac), 201)


@bp.route("/aircraft/<id>", methods=["GET"])
def get_aircraft(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "FuelTech", "LineManager", "Operator"})
    ac = db.aircraft.get(id)
    if ac is None:
        raise err(errors.ERR_NOT_FOUND, "Aircraft not found.")
    if role == "Operator" and user_id != ac["operator_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own aircraft.")
    return success(aircraft_view(ac), 200)


@bp.route("/aircraft", methods=["GET"])
def list_aircraft():
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "FuelTech", "BillingClerk", "LineManager", "Operator"})
    limit, offset = pagination_params()
    operator_id = request.args.get("operator_id")
    records = list(db.aircraft.values())
    if role == "Operator":
        records = [r for r in records if r["operator_id"] == user_id]
    if operator_id is not None:
        records = [r for r in records if r["operator_id"] == operator_id]
    window, total = paginate(records, limit, offset)
    return list_response([aircraft_view(r) for r in window], limit, offset, total)
