"""Changeovers (PRD §3.4): allergen cleaning matrix and the redo loop."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_CHANGEOVER_SEQUENCE,
    ERR_INVALID_STATE,
    ERR_LINE_FORMAT_MISMATCH,
    ERR_PRODUCT_DISCONTINUED,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import changeover_clean_level, serialize
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    path_entity,
)

bp = Blueprint("changeovers", __name__)

CHANGEOVER_SPEC = {
    "line_id": {"type": "string", "required": True},
    "to_product_id": {"type": "string", "required": True},
}

VERIFY_SPEC = {
    "outcome": {"type": "enum", "values": {"PASS", "FAIL"}, "required": True},
}


@bp.route("/changeovers", methods=["POST"])
def create_changeover():
    authenticate({"ProductionPlanner"})
    body = body_json()
    exist_body_fks(body, {
        "line_id": ("lines", "line"),
        "to_product_id": ("products", "product"),
    })
    check_shape(body, CHANGEOVER_SPEC)
    line = db.get("lines", body["line_id"])
    to_product = db.get("products", body["to_product_id"])
    # Priority 13: format compatibility.
    if to_product["format"] != line["format"]:
        raise ApiError(
            ERR_LINE_FORMAT_MISMATCH, 422, "to_product format differs from line format"
        )
    # Priority 14: the line must be IDLE (no run in flight, no open changeover).
    if line["status"] != "IDLE":
        raise ApiError(ERR_CHANGEOVER_SEQUENCE, 422, "line is not IDLE")
    # Priority 39: DISCONTINUED products cannot be referenced by new changeovers.
    if to_product["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCT_DISCONTINUED, 422, "to_product is not ACTIVE")
    level, duration = changeover_clean_level(line, to_product)
    changeover = db.new_entity("changeovers", {
        "line_id": line["id"],
        "from_product_id": line["last_product_id"],
        "to_product_id": to_product["id"],
        "required_clean_level": level,
        "duration_minutes": duration,
        "status": "REQUIRED",
        "completed_by": None,
        "verified_by": None,
    })
    line["status"] = "CLEANING"
    db.touch(line)
    return success_obj(serialize("changeovers", changeover), 201)


@bp.route("/changeovers", methods=["GET"])
def list_changeovers():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("changeovers"),
        ["line_id", "from_product_id", "to_product_id", "status"],
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("changeovers", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/changeovers/<changeover_id>", methods=["GET"])
def get_changeover(changeover_id):
    authenticate(ALL_ROLES)
    changeover = path_entity("changeovers", changeover_id, "changeover")
    return success_obj(serialize("changeovers", changeover))


@bp.route("/changeovers/<changeover_id>/complete", methods=["POST"])
def complete_changeover(changeover_id):
    user_id, _role = authenticate({"LineOperator"})
    changeover = path_entity("changeovers", changeover_id, "changeover")
    if changeover["status"] != "REQUIRED":
        raise ApiError(ERR_INVALID_STATE, 409, "changeover is not REQUIRED")
    changeover["completed_by"] = user_id
    changeover["status"] = "AWAITING_VERIFICATION"
    db.touch(changeover)
    return success_obj(serialize("changeovers", changeover))


@bp.route("/changeovers/<changeover_id>/verify", methods=["POST"])
def verify_changeover(changeover_id):
    user_id, _role = authenticate({"QAManager"})
    changeover = path_entity("changeovers", changeover_id, "changeover")
    body = body_json()
    check_shape(body, VERIFY_SPEC)
    if changeover["status"] != "AWAITING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, 409, "changeover is not AWAITING_VERIFICATION")
    # Segregation of duties (PRD §2.8): verifier != completer.
    if user_id == changeover["completed_by"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "verifier must differ from the completer",
        )
    if body["outcome"] == "PASS":
        changeover["verified_by"] = user_id
        changeover["status"] = "VERIFIED"
        line = db.get("lines", changeover["line_id"])
        if line is not None and line["status"] == "CLEANING":
            line["status"] = "IDLE"
            db.touch(line)
    else:
        # Redo loop: back to REQUIRED, completer cleared, line stays CLEANING.
        changeover["completed_by"] = None
        changeover["status"] = "REQUIRED"
    db.touch(changeover)
    return success_obj(serialize("changeovers", changeover))
