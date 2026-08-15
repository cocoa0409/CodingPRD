"""Screening lanes: create, open, close (PRD 3.5)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, exist_body_fks, pagination_params, paginate, apply_filters

bp = Blueprint("lanes", __name__, url_prefix="/port-ops")


@bp.route("/screening-lanes", methods=["POST"])
def create_lane():
    authenticate({"PortAuthorityAdmin"})
    body = body_json()
    exist_body_fks(body, {"terminal_id": ("terminals", "terminal")})
    check_shape(body, {
        "terminal_id": {"type": "string", "required": True},
        "lane_code": {"type": "string", "required": True},
    })
    # lane_code unique within the terminal (configuration label, PRD 3.5).
    for other in db.all_of("screening_lanes"):
        if other["terminal_id"] == body["terminal_id"] and other["lane_code"] == body["lane_code"]:
            raise ApiError(ERR_VALIDATION, 400, "lane_code must be unique within the terminal")
    lane = db.new_entity("screening_lanes", {
        "terminal_id": body["terminal_id"],
        "lane_code": body["lane_code"],
        "officers_assigned": 0,
        "status": "CLOSED",
    })
    return success_obj(db.public(lane), code=201)


@bp.route("/screening-lanes", methods=["GET"])
def list_lanes():
    authenticate(ANY)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("screening_lanes"), ["terminal_id", "status"])
    page, total, has_more = paginate([db.public(l) for l in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/screening-lanes/<lane_id>", methods=["GET"])
def get_lane(lane_id):
    authenticate(ANY)
    lane = db.get("screening_lanes", lane_id)
    if lane is None:
        raise ApiError(ERR_NOT_FOUND, 404, "screening lane not found")
    return success_obj(db.public(lane))


@bp.route("/screening-lanes/<lane_id>/open", methods=["POST"])
def open_lane(lane_id):
    authenticate({"TerminalOperator"})
    lane = db.get("screening_lanes", lane_id)
    if lane is None:
        raise ApiError(ERR_NOT_FOUND, 404, "screening lane not found")
    body = body_json()
    check_shape(body, {"officers_assigned": {"type": "integer", "required": True, "min": 1}})
    if lane["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "open requires status CLOSED")
    lane["status"] = "OPEN"
    lane["officers_assigned"] = body["officers_assigned"]
    db.touch(lane)
    return success_obj(db.public(lane))


@bp.route("/screening-lanes/<lane_id>/close", methods=["POST"])
def close_lane(lane_id):
    authenticate({"TerminalOperator"})
    lane = db.get("screening_lanes", lane_id)
    if lane is None:
        raise ApiError(ERR_NOT_FOUND, 404, "screening lane not found")
    if lane["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "close requires status OPEN")
    lane["status"] = "CLOSED"
    lane["officers_assigned"] = 0
    db.touch(lane)
    return success_obj(db.public(lane))
