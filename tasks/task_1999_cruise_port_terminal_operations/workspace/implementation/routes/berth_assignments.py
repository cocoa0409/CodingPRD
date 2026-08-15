"""Berth assignments: OCC-guarded create (supersede chain), confirm (PRD 3.3)."""

from flask import Blueprint, request

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_POSTURE_EMERGENCY,
    ERR_BERTH_NOT_FIT, ERR_WINDOW_NOT_CONTAINED, ERR_BERTH_WINDOW_CONFLICT,
    ERR_STALE_VERSION, ERR_VESSEL_SCOPE,
)
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, raw_body, check_shape, pagination_params, paginate, apply_filters

bp = Blueprint("berth_assignments", __name__, url_prefix="/port-ops")


def _get_asg_or_404(asg_id):
    asg = db.get("berth_assignments", asg_id)
    if asg is None:
        raise ApiError(ERR_NOT_FOUND, 404, "berth assignment not found")
    return asg


@bp.route("/port-calls/<call_id>/berth-assignments", methods=["POST"])
def create_assignment(call_id):
    authenticate({"Harbormaster"})
    # Priority 3: existence, path id first, then body FK.
    call = db.get("port_calls", call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    body = body_json()
    berth = None
    if body.get("berth_id") is not None:
        berth = db.get("berths", body["berth_id"])
        if berth is None:
            raise ApiError(ERR_NOT_FOUND, 404, "berth not found")
    # Priority 5: OCC on the parent port call's version.
    raw = raw_body()
    if raw.get("expected_port_call_version") is not None:
        if raw["expected_port_call_version"] != call["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           "expected_port_call_version does not match the call's current version")
    # Priority 6: body shape.
    check_shape(body, {
        "berth_id": {"type": "string", "required": True},
        "window_start": {"type": "datetime", "required": True},
        "window_end": {"type": "datetime", "required": True},
        "expected_port_call_version": {"type": "integer", "required": True},
    })
    # Priority 9: posture gate.
    term = services.terminal_of_call(call)
    posture, _a, _o, _f = services.posture_of(term)
    if posture == "EMERGENCY":
        raise ApiError(ERR_POSTURE_EMERGENCY, 409,
                       "terminal posture is EMERGENCY; assignment creation is gated")
    # Priority 10: berth physical fit.
    vessel = db.get("vessels", call["vessel_id"])
    if not services.berth_fits(berth, vessel):
        raise ApiError(ERR_BERTH_NOT_FIT, 422,
                       "berth does not physically fit the vessel")
    # Priority 13: window containment of the call's schedule.
    candidate = {"window_start": body["window_start"], "window_end": body["window_end"]}
    if not services.window_contains_schedule(candidate, call):
        raise ApiError(ERR_WINDOW_NOT_CONTAINED, 422,
                       "assignment window does not contain the call's schedule")
    # Side effect: supersede the call's existing live assignment; when a
    # CONFIRMED assignment is superseded the window-loss chain fires (the new
    # assignment's window counts as a remaining live window).
    superseded_confirmed = False
    for asg in services.assignments_of_call(call["id"]):
        if asg["status"] in ("TENTATIVE", "CONFIRMED"):
            if asg["status"] == "CONFIRMED":
                superseded_confirmed = True
            asg["status"] = "SUPERSEDED"
            db.touch(asg)
    new_asg = db.new_entity("berth_assignments", {
        "port_call_id": call["id"],
        "berth_id": body["berth_id"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "TENTATIVE",
    })
    if superseded_confirmed:
        services.window_loss_chain(call)
    db.touch(call)
    return success_obj(db.public(new_asg), code=201)


@bp.route("/berth-assignments", methods=["GET"])
def list_assignments():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("berth_assignments")
    if role == "VesselAgent":
        port_call_id = request.args.get("port_call_id")
        if port_call_id is not None:
            call = db.get("port_calls", port_call_id)
            if call is not None and call["vessel_id"] != user_id:
                raise ApiError(ERR_VESSEL_SCOPE, 403,
                               "vessel agent may only read its own vessel's calls")
        items = [
            a for a in items
            if (db.get("port_calls", a["port_call_id"]) or {}).get("vessel_id") == user_id
        ]
    items = apply_filters(items, ["port_call_id", "berth_id", "status"])
    page, total, has_more = paginate([db.public(a) for a in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/berth-assignments/<asg_id>", methods=["GET"])
def get_assignment(asg_id):
    user_id, role = authenticate(ANY)
    asg = _get_asg_or_404(asg_id)
    if role == "VesselAgent":
        call = db.get("port_calls", asg["port_call_id"])
        if call is None or call["vessel_id"] != user_id:
            raise ApiError(ERR_VESSEL_SCOPE, 403,
                           "vessel agent may only read its own vessel's calls")
    return success_obj(db.public(asg))


@bp.route("/berth-assignments/<asg_id>/confirm", methods=["POST"])
def confirm(asg_id):
    authenticate({"Harbormaster"})
    asg = _get_asg_or_404(asg_id)
    # Priority 8: state gate -- still TENTATIVE, berth still ACTIVE.
    if asg["status"] != "TENTATIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not TENTATIVE")
    berth = db.get("berths", asg["berth_id"])
    if berth is None:
        raise ApiError(ERR_NOT_FOUND, 404, "berth not found")
    if berth["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "berth is not ACTIVE")
    call = db.get("port_calls", asg["port_call_id"])
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    # Priority 9: posture gate.
    term = services.terminal_of_call(call)
    posture, _a, _o, _f = services.posture_of(term)
    if posture == "EMERGENCY":
        raise ApiError(ERR_POSTURE_EMERGENCY, 409,
                       "terminal posture is EMERGENCY; confirmation is gated")
    # Priority 10: berth physical fit.
    vessel = db.get("vessels", call["vessel_id"])
    if not services.berth_fits(berth, vessel):
        raise ApiError(ERR_BERTH_NOT_FIT, 422,
                       "berth does not physically fit the vessel")
    # Priority 13: containment of the call's schedule.
    if not services.window_contains_schedule(asg, call):
        raise ApiError(ERR_WINDOW_NOT_CONTAINED, 422,
                       "assignment window does not contain the call's schedule")
    # Priority 14: buffered overlap against same-berth CONFIRMED/ACTIVE windows.
    if services.window_conflict(asg["berth_id"], asg, exclude_id=asg["id"]):
        raise ApiError(ERR_BERTH_WINDOW_CONFLICT, 409,
                       "same-berth window within the 120-minute buffer")
    asg["status"] = "CONFIRMED"
    db.touch(asg)
    return success_obj(db.public(asg))
