"""Serial number endpoints (list / get / ship)."""

from flask import Blueprint, request

from db import db, public
from errors import (
    ApiError,
    ERR_SERIAL_NOT_FOUND,
    ERR_SERIAL_NOT_SHIPPABLE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import ship_serial
from validate import json_body, no_unknown, paginate

bp = Blueprint("serials", __name__)

MP = "ManufacturingPlanner"


def get_serial(serial_id):
    s = db.serials.get(serial_id)
    if s is None:
        raise ApiError(ERR_SERIAL_NOT_FOUND, 404, "Serial %s not found" % serial_id)
    return s


@bp.route("/api/serials", methods=["GET"])
def list_serials():
    require_roles(*ALL_ROLES)
    items = list(db.serials.values())
    wo_id = request.args.get("wo_id")
    cert_id = request.args.get("material_cert_id")
    status = request.args.get("status")
    if wo_id is not None:
        items = [s for s in items if s["wo_id"] == wo_id]
    if cert_id is not None:
        items = [s for s in items if s["material_cert_id"] == cert_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, pagination = paginate(items, request.args)
    return success_list(page, pagination)


@bp.route("/api/serials/<serialId>", methods=["GET"])
def get_one_serial(serialId):
    require_roles(*ALL_ROLES)
    return success_object(public(get_serial(serialId)))


@bp.route("/api/serials/<serialId>/ship", methods=["POST"])
def ship_one(serialId):
    require_roles(MP)
    data = json_body()
    no_unknown(data, set())
    s = get_serial(serialId)
    if s["status"] != "CREATED":
        raise ApiError(ERR_SERIAL_NOT_SHIPPABLE, 409, "Serial ship requires CREATED")
    ship_serial(s)
    return success_object(public(s))
