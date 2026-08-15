"""FieldTechnician endpoints."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION, ERR_TECHNICIAN_HAS_OPEN_WORK
from middleware import require_roles, ALL_ROLES, body, req_str
from response import success, list_response, created_sorted
from serializers import ser_technician

bp = Blueprint("technicians", __name__)


def _get_tech(tid):
    t = db.technicians.get(tid)
    if not t:
        raise ApiError(ERR_NOT_FOUND, "FieldTechnician not found", 404)
    return t


@bp.route("/field-technicians", methods=["POST"])
def create():
    require_roles("MeterOpsAdmin")
    data = body()
    display_name = req_str(data, "display_name")
    rec = {"display_name": display_name, "technician_status": "ACTIVE"}
    stamp_new(rec)
    db.technicians[rec["id"]] = rec
    return success(ser_technician(rec), code=201)


@bp.route("/field-technicians", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.technicians.values())
    status = request.args.get("technician_status")
    if status is not None:
        items = [t for t in items if t["technician_status"] == status]
    return list_response([ser_technician(t) for t in created_sorted(items)])


@bp.route("/field-technicians/<tid>", methods=["GET"])
def get_one(tid):
    require_roles(*ALL_ROLES)
    return success(ser_technician(_get_tech(tid)), code=200)


@bp.route("/field-technicians/<tid>/deactivate", methods=["POST"])
def deactivate(tid):
    require_roles("MeterOpsAdmin")
    t = _get_tech(tid)
    if t["technician_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Technician is not ACTIVE", 409)
    committed_route = any(
        r["technician_id"] == tid and r["route_status"] in ("ASSIGNED", "IN_PROGRESS")
        for r in db.routes.values()
    )
    committed_order = any(
        w["technician_id"] == tid and w["work_order_status"] in ("DISPATCHED", "IN_PROGRESS")
        for w in db.work_orders.values()
    )
    if committed_route or committed_order:
        raise ApiError(
            ERR_TECHNICIAN_HAS_OPEN_WORK,
            "Technician has open route or work-order commitments",
            409,
        )
    t["technician_status"] = "INACTIVE"
    touch(t)
    return success(ser_technician(t), code=200)
