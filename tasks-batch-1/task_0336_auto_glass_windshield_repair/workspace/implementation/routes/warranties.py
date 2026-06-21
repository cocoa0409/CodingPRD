"""Warranty: fetch, void (PRD 3.7)."""
from flask import Blueprint, g

import db
import errors
import response
from errors import ApiError
from middleware import require_roles
from services import helpers as H

bp = Blueprint("warranties", __name__)


@bp.route("/warranties/<wid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager", "Customer")
def get_warranty(wid):
    warranty = H.get_warranty(wid)
    if g.role == "Customer":
        wo = db.work_orders.get(warranty["work_order_id"])
        if wo is not None:
            H.enforce_work_order_owner(wo)
    return response.success(H.view(warranty))


@bp.route("/warranties/<wid>/void", methods=["POST"])
@require_roles("ShopManager")
def void_warranty(wid):
    warranty = H.get_warranty(wid)
    if warranty["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Warranty is not ACTIVE.")
    warranty["status"] = "VOID"
    db.touch(warranty)
    return response.success(H.view(warranty))
