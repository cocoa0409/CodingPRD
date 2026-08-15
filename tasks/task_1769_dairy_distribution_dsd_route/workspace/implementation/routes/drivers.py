"""Driver endpoints: hire, get, list, weekly settlement."""

from flask import Blueprint

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_enum,
    base_fields, paginate, err, parse_date,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_DISTRIBUTOR_NOT_FOUND, ERR_DRIVER_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
)
from serializers import serialize_driver
from services import weekly_settlement

bp = Blueprint("drivers", __name__)


@bp.post("/dairy/drivers")
def create_driver():
    user_id, _role = require_role("DistributorOwner")
    body = get_json_body()
    check_unknown_fields(body, {"distributor_id", "name", "cdl_class"})
    require_fields(body, ["distributor_id", "name", "cdl_class"])
    # Ownership (priority 3): the employer must be the caller's distributorship.
    if body["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "distributor_id must equal the caller's X-User-ID")
    distributor = DB.distributors.get(body["distributor_id"])
    if distributor is None:
        raise err(ERR_DISTRIBUTOR_NOT_FOUND, "Distributor id not found")
    name = body["name"]
    if not isinstance(name, str):
        raise err(ERR_INVALID_REQUEST, "name must be a string")
    cdl_class = opt_enum(body, "cdl_class", {"A", "B"})
    d = base_fields()
    d.update({
        "distributor_id": distributor["id"],
        "name": name,
        "cdl_class": cdl_class,
    })
    DB.drivers[d["id"]] = d
    return success_object(serialize_driver(d), status=201)


@bp.get("/dairy/drivers/<driverId>")
def get_driver(driverId):
    require_any()
    d = DB.drivers.get(driverId)
    if d is None:
        raise err(ERR_DRIVER_NOT_FOUND, "Driver id not found")
    return success_object(serialize_driver(d))


@bp.get("/dairy/distributors/<distId>/drivers")
def list_distributor_drivers(distId):
    require_any()
    d = DB.distributors.get(distId)
    if d is None:
        raise err(ERR_DISTRIBUTOR_NOT_FOUND, "Distributor id not found")
    items = [x for x in DB.drivers.values() if x["distributor_id"] == distId]
    items.sort(key=lambda x: x["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_driver(x) for x in page], limit, offset, total)


@bp.get("/dairy/drivers/<driverId>/weekly-settlement")
def get_weekly_settlement(driverId):
    user_id, role = require_role("DistributorOwner", "RouteDriver")
    d = DB.drivers.get(driverId)
    if d is None:
        raise err(ERR_DRIVER_NOT_FOUND, "Driver id not found")
    if role == "DistributorOwner":
        if d["distributor_id"] != user_id:
            raise err(ERR_OWNERSHIP_MISMATCH, "Driver belongs to another distributor")
    else:  # RouteDriver may read only their own settlement
        if d["id"] != user_id:
            raise err(ERR_OWNERSHIP_MISMATCH, "Driver may read only their own settlement")
    from flask import request
    week_start = request.args.get("week_start")
    if not week_start:
        raise err(ERR_INVALID_REQUEST, "week_start query parameter is required")
    try:
        ws = parse_date(week_start)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "week_start must be a YYYY-MM-DD date")
    return success_object(weekly_settlement(driverId, ws))
