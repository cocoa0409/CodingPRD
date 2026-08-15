"""Vessels: registry create/list/get (PRD 3.1)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, exist_body_fks, pagination_params, paginate, apply_filters

bp = Blueprint("vessels", __name__, url_prefix="/port-ops")


@bp.route("/vessels", methods=["POST"])
def create_vessel():
    authenticate({"PortAuthorityAdmin"})
    body = body_json()
    exist_body_fks(body, {"terminal_id": ("terminals", "terminal")})
    check_shape(body, {
        "terminal_id": {"type": "string", "required": True},
        "name": {"type": "string", "required": True},
        "loa_ft": {"type": "integer", "required": True, "min": 50},
        "draft_ft": {"type": "number", "required": True, "gt": 0},
        "pax_capacity": {"type": "integer", "required": True, "min": 1},
        "crew_count": {"type": "integer", "required": True, "min": 0},
    })
    vessel = db.new_entity("vessels", {
        "terminal_id": body["terminal_id"],
        "name": body["name"],
        "loa_ft": body["loa_ft"],
        "draft_ft": body["draft_ft"],
        "pax_capacity": body["pax_capacity"],
        "crew_count": body["crew_count"],
    })
    return success_obj(db.public(vessel), code=201)


@bp.route("/vessels", methods=["GET"])
def list_vessels():
    authenticate(ANY)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("vessels"), ["terminal_id"])
    page, total, has_more = paginate([db.public(v) for v in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/vessels/<vessel_id>", methods=["GET"])
def get_vessel(vessel_id):
    authenticate(ANY)
    vessel = db.get("vessels", vessel_id)
    if vessel is None:
        raise ApiError(ERR_NOT_FOUND, 404, "vessel not found")
    return success_obj(db.public(vessel))
