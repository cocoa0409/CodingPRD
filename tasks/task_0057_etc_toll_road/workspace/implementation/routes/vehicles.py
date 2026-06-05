from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common, touch
from middleware import get_auth, require_roles
from response import success
from util import (get_body, require_str, require_int, require_bool, paginate,
                  sorted_by_created)
from serialize import public, public_list

bp = Blueprint("vehicles", __name__)


def _get_vehicle_or_404(vid):
    v = db.vehicles.get(vid)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Vehicle not found")
    return v


@bp.post("/etc/vehicles")
def create_vehicle():
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator"})
    body = get_body()
    account_id = require_str(body, "account_id")
    acc = db.accounts.get(account_id)
    if acc is None:
        raise err(errors.ERR_NOT_FOUND, "Account not found")
    if role == "AccountHolder" and account_id != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning account")
    plate_number = require_str(body, "plate_number")
    plate_state_code = require_str(body, "plate_state_code")
    hov_capable = require_bool(body, "hov_capable", required=False, default=False)
    axle_count = require_int(body, "axle_count", required=False, default=2, min_value=2)

    veh = {
        "account_id": account_id,
        "plate_number": plate_number.upper(),
        "plate_state_code": plate_state_code,
        "registration_status": "REGISTERED",
        "hov_capable": hov_capable,
        "axle_count": axle_count,
    }
    init_common(veh)
    db.vehicles[veh["id"]] = veh
    return success(public(veh), status=201)


@bp.get("/etc/vehicles/<vid>")
def get_vehicle(vid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    v = _get_vehicle_or_404(vid)
    if role == "AccountHolder" and v["account_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning account")
    return success(public(v))


@bp.get("/etc/vehicles")
def list_vehicles():
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    items = list(db.vehicles.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [v for v in items if v["account_id"] == account_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)


@bp.post("/etc/vehicles/<vid>/lapse-registration")
def lapse_registration(vid):
    _, role = get_auth()
    require_roles(role, {"TollOperator", "SystemAdmin"})
    v = _get_vehicle_or_404(vid)
    v["registration_status"] = "LAPSED"
    touch(v)
    return success(public(v))
