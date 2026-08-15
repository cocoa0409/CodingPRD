"""Berths: create/list/get, out-of-service, return-to-service (PRD 3.1)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, exist_body_fks, pagination_params, paginate, apply_filters

bp = Blueprint("berths", __name__, url_prefix="/port-ops")


@bp.route("/berths", methods=["POST"])
def create_berth():
    authenticate({"PortAuthorityAdmin"})
    body = body_json()
    exist_body_fks(body, {"terminal_id": ("terminals", "terminal")})
    check_shape(body, {
        "terminal_id": {"type": "string", "required": True},
        "berth_code": {"type": "string", "required": True},
        "length_ft": {"type": "integer", "required": True, "min": 100},
        "max_draft_ft": {"type": "number", "required": True, "gt": 0},
    })
    # Priority 15: berth_code unique within the terminal.
    for other in db.all_of("berths"):
        if other["terminal_id"] == body["terminal_id"] and other["berth_code"] == body["berth_code"]:
            raise ApiError(ERR_VALIDATION, 400, "berth_code must be unique within the terminal")
    berth = db.new_entity("berths", {
        "terminal_id": body["terminal_id"],
        "berth_code": body["berth_code"],
        "length_ft": body["length_ft"],
        "max_draft_ft": body["max_draft_ft"],
        "status": "ACTIVE",
    })
    return success_obj(db.public(berth), code=201)


@bp.route("/berths", methods=["GET"])
def list_berths():
    authenticate(ANY)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("berths"), ["terminal_id", "status"])
    page, total, has_more = paginate([db.public(b) for b in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/berths/<berth_id>", methods=["GET"])
def get_berth(berth_id):
    authenticate(ANY)
    berth = db.get("berths", berth_id)
    if berth is None:
        raise ApiError(ERR_NOT_FOUND, 404, "berth not found")
    return success_obj(db.public(berth))


@bp.route("/berths/<berth_id>/out-of-service", methods=["POST"])
def out_of_service(berth_id):
    authenticate({"PortAuthorityAdmin"})
    berth = db.get("berths", berth_id)
    if berth is None:
        raise ApiError(ERR_NOT_FOUND, 404, "berth not found")
    if berth["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "berth is not ACTIVE")
    # Refused while any assignment on this berth is ACTIVE; TENTATIVE
    # assignments are left in place and only caught at confirmation time.
    for asg in db.all_of("berth_assignments"):
        if asg["berth_id"] == berth["id"] and asg["status"] == "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409, "berth has an ACTIVE berth assignment")
    berth["status"] = "OUT_OF_SERVICE"
    db.touch(berth)
    return success_obj(db.public(berth))


@bp.route("/berths/<berth_id>/return-to-service", methods=["POST"])
def return_to_service(berth_id):
    authenticate({"PortAuthorityAdmin"})
    berth = db.get("berths", berth_id)
    if berth is None:
        raise ApiError(ERR_NOT_FOUND, 404, "berth not found")
    if berth["status"] != "OUT_OF_SERVICE":
        raise ApiError(ERR_INVALID_STATE, 409, "berth is not OUT_OF_SERVICE")
    berth["status"] = "ACTIVE"
    db.touch(berth)
    return success_obj(db.public(berth))
