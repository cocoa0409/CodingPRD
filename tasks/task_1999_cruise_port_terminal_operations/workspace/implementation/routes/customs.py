"""Customs cases: one per call; DRAFT/FILED/HELD/CLEARED flows (PRD 3.5)."""

from flask import Blueprint, request

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_DUPLICATE_CUSTOMS_CASE,
    ERR_VESSEL_SCOPE,
)
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, pagination_params, paginate, apply_filters

bp = Blueprint("customs", __name__, url_prefix="/port-ops")

_PRE_DEPARTURE_STATES = ("SCHEDULED", "DELAYED", "ARRIVED", "TURNAROUND")


def _get_case_or_404(case_id):
    case = db.get("customs_cases", case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "customs case not found")
    return case


@bp.route("/port-calls/<call_id>/customs-cases", methods=["POST"])
def create_case(call_id):
    authenticate({"CustomsOfficer"})
    call = db.get("port_calls", call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    # Priority 8: parent-state gate on child creation.
    if call["status"] not in _PRE_DEPARTURE_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "customs case creation requires a pre-departure call state")
    # Priority 16: at most one case per port call.
    if services.customs_case_of(call["id"]) is not None:
        raise ApiError(ERR_DUPLICATE_CUSTOMS_CASE, 409,
                       "a customs case already exists for this port call")
    case = db.new_entity("customs_cases", {
        "port_call_id": call["id"],
        "status": "DRAFT",
        "hold_reason": None,
    })
    return success_obj(db.public(case), code=201)


@bp.route("/customs-cases", methods=["GET"])
def list_cases():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("customs_cases")
    if role == "VesselAgent":
        port_call_id = request.args.get("port_call_id")
        if port_call_id is not None:
            call = db.get("port_calls", port_call_id)
            if call is not None and call["vessel_id"] != user_id:
                raise ApiError(ERR_VESSEL_SCOPE, 403,
                               "vessel agent may only read its own vessel's calls")
        items = [
            c for c in items
            if (db.get("port_calls", c["port_call_id"]) or {}).get("vessel_id") == user_id
        ]
    items = apply_filters(items, ["port_call_id", "status"])
    page, total, has_more = paginate([db.public(c) for c in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/customs-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    user_id, role = authenticate(ANY)
    case = _get_case_or_404(case_id)
    if role == "VesselAgent":
        call = db.get("port_calls", case["port_call_id"])
        if call is None or call["vessel_id"] != user_id:
            raise ApiError(ERR_VESSEL_SCOPE, 403,
                           "vessel agent may only read its own vessel's calls")
    return success_obj(db.public(case))


@bp.route("/customs-cases/<case_id>/file", methods=["POST"])
def file_case(case_id):
    authenticate({"CustomsOfficer"})
    case = _get_case_or_404(case_id)
    if case["status"] == "DRAFT":
        # DRAFT -> FILED is gated on the call still being pre-departure.
        call = db.get("port_calls", case["port_call_id"])
        if call is None or call["status"] not in _PRE_DEPARTURE_STATES:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "filing requires the call to be in a pre-departure state")
    elif case["status"] == "HELD":
        pass  # Revision loop HELD -> FILED carries no preconditions.
    else:
        raise ApiError(ERR_INVALID_STATE, 409, "file requires status DRAFT or HELD")
    case["status"] = "FILED"
    db.touch(case)
    return success_obj(db.public(case))


@bp.route("/customs-cases/<case_id>/hold", methods=["POST"])
def hold_case(case_id):
    authenticate({"CustomsOfficer"})
    case = _get_case_or_404(case_id)
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": True}})
    if case["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "hold requires status FILED")
    case["status"] = "HELD"
    case["hold_reason"] = body["reason"]
    db.touch(case)
    services.cascade_customs_hold(case)
    return success_obj(db.public(case))


@bp.route("/customs-cases/<case_id>/clear", methods=["POST"])
def clear_case(case_id):
    authenticate({"CustomsOfficer"})
    case = _get_case_or_404(case_id)
    if case["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, 409, "clear requires status FILED")
    case["status"] = "CLEARED"
    db.touch(case)
    return success_obj(db.public(case))
