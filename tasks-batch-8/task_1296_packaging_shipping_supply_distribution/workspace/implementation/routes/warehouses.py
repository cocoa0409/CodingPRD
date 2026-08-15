"""Warehouse endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import err_invalid_request, err_not_found, err_invalid_state
from middleware import (require_roles, get_json_body, require_str, require_int,
                        optional_bool, optional_int)
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_warehouse
from util import valid_hhmm, valid_timezone

bp = Blueprint("warehouses", __name__)
PREFIX = "/packaging-distribution"

WAREHOUSE_CODES = {"ATL", "RNO", "DFW"}
WAREHOUSE_STATUSES = {"ACTIVE", "INACTIVE"}
LIST_ROLES = ("PlatformAdmin", "CatalogManager", "CustomerService",
              "WarehouseOps", "Buyer", "AccountApprover")


def _get_warehouse(warehouse_id):
    w = db.warehouses.get(warehouse_id)
    if w is None:
        raise err_not_found("Warehouse not found.")
    return w


@bp.route(f"{PREFIX}/warehouses", methods=["POST"])
@require_roles("PlatformAdmin")
def create_warehouse():
    body = get_json_body(required=True)
    code = require_str(body, "code")
    if code not in WAREHOUSE_CODES:
        raise err_invalid_request("Field 'code' must be one of ATL | RNO | DFW.")
    if any(w["code"] == code for w in db.warehouses.values()):
        raise err_invalid_request("Field 'code' must be unique.")
    name = require_str(body, "name")
    zone = require_int(body, "zone")
    if zone < 1 or zone > 8:
        raise err_invalid_request("Field 'zone' must be in 1..8.")
    ship_cutoff_time = require_str(body, "ship_cutoff_time")
    if not valid_hhmm(ship_cutoff_time):
        raise err_invalid_request("Field 'ship_cutoff_time' must be HH:MM 24h format.")
    timezone = require_str(body, "timezone")
    if not valid_timezone(timezone):
        raise err_invalid_request("Field 'timezone' must be a valid IANA timezone name.")
    oversize_capable = optional_bool(body, "oversize_capable")
    if oversize_capable is None:
        oversize_capable = True
    press_count = optional_int(body, "press_count")
    if press_count is None:
        press_count = 1
    if press_count < 1:
        raise err_invalid_request("Field 'press_count' must be >= 1.")

    now = db.now()
    w = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "code": code,
        "name": name,
        "zone": zone,
        "ship_cutoff_time": ship_cutoff_time,
        "timezone": timezone,
        "oversize_capable": oversize_capable,
        "press_count": press_count,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.warehouses[w["id"]] = w
    return success_object(ser_warehouse(w), status=201)


@bp.route(f"{PREFIX}/warehouses", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_warehouses():
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    if status_f is not None and status_f not in WAREHOUSE_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    items = sorted(db.warehouses.values(), key=lambda w: (w["created_at"], w["_seq"]))
    if status_f is not None:
        items = [w for w in items if w["status"] == status_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_warehouse(w) for w in page], pagination)


@bp.route(f"{PREFIX}/warehouses/<warehouse_id>", methods=["GET"])
@require_roles("PlatformAdmin", "CatalogManager", "CustomerService", "WarehouseOps")
def get_warehouse(warehouse_id):
    return success_object(ser_warehouse(_get_warehouse(warehouse_id)))


@bp.route(f"{PREFIX}/warehouses/<warehouse_id>/deactivate", methods=["POST"])
@require_roles("PlatformAdmin")
def deactivate_warehouse(warehouse_id):
    w = _get_warehouse(warehouse_id)
    if w["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE warehouse can be deactivated.")
    w["status"] = "INACTIVE"
    db.touch(w)
    return success_object(ser_warehouse(w))


@bp.route(f"{PREFIX}/warehouses/<warehouse_id>/activate", methods=["POST"])
@require_roles("PlatformAdmin")
def activate_warehouse(warehouse_id):
    w = _get_warehouse(warehouse_id)
    if w["status"] != "INACTIVE":
        raise err_invalid_state("Only an INACTIVE warehouse can be activated.")
    w["status"] = "ACTIVE"
    db.touch(w)
    return success_object(ser_warehouse(w))
