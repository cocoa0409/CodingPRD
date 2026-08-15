"""Cylinder assets: the branch float, registration, retirement, reconciliation."""
from flask import Blueprint

import db
from db import store, new_common, new_id, touch
from errors import ApiError
from middleware import require_roles, body
from response import ok, created, list_response, filter_param

bp = Blueprint("cylinders", __name__)

_ROLES = ("CounterRep", "BranchManager", "RouteDriver")


def serial_in_use(serial):
    if any(a["serial_no"] == serial for a in store.cylinder_assets.values()):
        return True
    return any(m["serial_no"] == serial for m in store.machines.values())


def get_asset(aid):
    asset = store.cylinder_assets.get(aid)
    if asset is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CylinderAsset not found")
    return asset


@bp.route("/cylinder-assets", methods=["POST"])
@require_roles("BranchManager")
def create_asset():
    b = body()
    serial = b.get("serial_no")
    grade = b.get("gas_grade")
    size = b.get("size")
    if not isinstance(serial, str) or not serial:
        raise ApiError("ERR_VALIDATION", 400, "serial_no is required")
    if grade not in db.GAS_GRADES:
        raise ApiError("ERR_VALIDATION", 400, "gas_grade is invalid")
    if size not in ("SMALL", "MEDIUM", "LARGE"):
        raise ApiError("ERR_VALIDATION", 400, "size must be SMALL, MEDIUM or LARGE")
    # Serials share one uniqueness pool across cylinders and machines.
    if serial_in_use(serial):
        raise ApiError("ERR_DUPLICATE_SERIAL", 409, "serial_no already exists")
    asset = {
        "id": new_id(),
        "serial_no": serial,
        "gas_grade": grade,
        "size": size,
        "status": "FULL",
        "holder_customer_id": None,
        "rental_agreement_id": None,
    }
    new_common(asset)
    store.cylinder_assets[asset["id"]] = asset
    return created(asset)


@bp.route("/cylinder-assets", methods=["GET"])
@require_roles(*_ROLES)
def list_assets():
    rows = list(store.cylinder_assets.values())
    rows = filter_param(rows, "status")
    rows = filter_param(rows, "gas_grade")
    rows = filter_param(rows, "holder_customer_id")
    rows = filter_param(rows, "rental_agreement_id")
    return list_response(rows)


@bp.route("/cylinder-assets/float-summary", methods=["GET"])
@require_roles(*_ROLES)
def float_summary():
    """Per-grade float reconciliation (scaffold calculations.float_reconciliation).

    Declared before /cylinder-assets/{id}; the literal segment wins.
    total excludes retired assets; retired counts are reported separately.
    """
    grades = []
    total_assets = 0
    retired_assets = 0
    for grade in db.GAS_GRADES:
        full = empty = out = retired = 0
        for a in store.cylinder_assets.values():
            if a["gas_grade"] != grade:
                continue
            if a["status"] == "FULL":
                full += 1
            elif a["status"] == "EMPTY":
                empty += 1
            elif a["status"] == "OUT":
                out += 1
            elif a["status"] == "RETIRED":
                retired += 1
        grades.append({
            "gas_grade": grade,
            "full": full,
            "empty": empty,
            "out": out,
            "retired": retired,
            "total": full + empty + out,
        })
        total_assets += full + empty + out
        retired_assets += retired
    return ok({"grades": grades, "total_assets": total_assets,
               "retired_assets": retired_assets})


@bp.route("/cylinder-assets/<aid>", methods=["GET"])
@require_roles(*_ROLES)
def get_one_asset(aid):
    return ok(get_asset(aid))


@bp.route("/cylinder-assets/<aid>/retire", methods=["POST"])
@require_roles("BranchManager")
def retire_asset(aid):
    asset = get_asset(aid)
    # Condemnation is permitted only from FULL or EMPTY, never while OUT.
    if asset["status"] not in ("FULL", "EMPTY"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a FULL or EMPTY cylinder can be retired")
    asset["status"] = "RETIRED"
    touch(asset)
    return ok(asset)
