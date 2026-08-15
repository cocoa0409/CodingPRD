"""MattressUnit read endpoints."""
from flask import Blueprint, request

import db
import errors
import middleware
import response

bp = Blueprint("units", __name__)


def unit_view(u):
    return {
        "id": u["id"],
        "serial_no": u["serial_no"],
        "order_id": u["order_id"],
        "model_id": u["model_id"],
        "retailer_id": u["retailer_id"],
        "foam_batch_id": u["foam_batch_id"],
        "law_label_id": u["law_label_id"],
        "purchase_price_cents": u["purchase_price_cents"],
        "delivered_at": u["delivered_at"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def get_unit(unit_id):
    u = db.units.get(unit_id)
    if u is None:
        errors.raise_err(errors.ERR_UNIT_NOT_FOUND, "unit not found")
    return u


@bp.route("/units", methods=["GET"])
def list_units():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.units.values())
    for param in ("order_id", "model_id", "retailer_id", "foam_batch_id", "law_label_id", "status"):
        q = request.args.get(param)
        if q is not None:
            items = [u for u in items if u[param] == q]
    items.sort(key=lambda u: u["_seq"])
    return response.success_list([unit_view(u) for u in items])


@bp.route("/units/<unitId>", methods=["GET"])
def get_one_unit(unitId):
    middleware.require_roles(middleware.ALL_ROLES)
    u = get_unit(unitId)
    return response.success_object(unit_view(u))
