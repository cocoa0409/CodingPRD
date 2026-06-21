"""Road-hazard warranty routes — read only (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import lookup_path_or_404

bp = Blueprint("road_hazard", __name__)


@bp.get("/road-hazard-warranties/<wid>")
def get_warranty(wid: str):
    require_auth(["ServiceAdvisor", "Customer"])()
    w = lookup_path_or_404(db.road_hazard_warranties, wid, "RoadHazardWarranty")
    return ok_object(w, 200)


@bp.get("/road-hazard-warranties")
def list_warranties():
    require_auth(["ServiceAdvisor", "Customer"])()
    limit, offset = paginate_params(request.args)
    items = list(db.road_hazard_warranties.values())
    if "work_order_line_id" in request.args:
        items = [w for w in items
                 if w["work_order_line_id"] == request.args["work_order_line_id"]]
    if "tire_model_id" in request.args:
        items = [w for w in items
                 if w["tire_model_id"] == request.args["tire_model_id"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
