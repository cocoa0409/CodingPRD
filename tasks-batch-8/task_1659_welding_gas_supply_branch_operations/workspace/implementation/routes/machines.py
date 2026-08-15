"""Rental weld machines."""
from flask import Blueprint

from db import store, new_common, new_id, is_int
from errors import ApiError
from middleware import require_roles, body
from response import ok, created
from routes.cylinders import serial_in_use

bp = Blueprint("machines", __name__)


@bp.route("/machines", methods=["POST"])
@require_roles("BranchManager")
def create_machine():
    b = body()
    model = b.get("model")
    serial = b.get("serial_no")
    daily = b.get("daily_rate_cents")
    weekly = b.get("weekly_rate_cents")
    monthly = b.get("monthly_rate_cents")
    if not isinstance(model, str) or not model:
        raise ApiError("ERR_VALIDATION", 400, "model is required")
    if not isinstance(serial, str) or not serial:
        raise ApiError("ERR_VALIDATION", 400, "serial_no is required")
    for field, value in (("daily_rate_cents", daily), ("weekly_rate_cents", weekly),
                         ("monthly_rate_cents", monthly)):
        if not is_int(value) or value <= 0:
            raise ApiError("ERR_VALIDATION", 400, "%s must be an integer > 0" % field)
    if serial_in_use(serial):
        raise ApiError("ERR_DUPLICATE_SERIAL", 409, "serial_no already exists")
    machine = {
        "id": new_id(),
        "model": model,
        "serial_no": serial,
        "daily_rate_cents": daily,
        "weekly_rate_cents": weekly,
        "monthly_rate_cents": monthly,
        "status": "AVAILABLE",
    }
    new_common(machine)
    store.machines[machine["id"]] = machine
    return created(machine)


@bp.route("/machines/<mid>", methods=["GET"])
@require_roles("CounterRep", "BranchManager", "RouteDriver", "ServiceTech")
def get_machine(mid):
    machine = store.machines.get(mid)
    if machine is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Machine not found")
    return ok(machine)
