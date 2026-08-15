"""Pen endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_PEN_NOT_FOUND, ERR_DUPLICATE_PEN_CODE, \
    ERR_INVALID_STATE_TRANSITION, raise_err
from serializers import pen_out, pen_assignment_out, feed_call_out
from services import pen_service
from util import body_json, get_or_404, list_response, new_record, bump, \
    req_str, req_int, success_object

bp = Blueprint("pens", __name__)


@bp.route("/feedlot/pens", methods=["POST"])
def create_pen():
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    body = body_json()
    pen_code = req_str(body, "pen_code")
    capacity_head = req_int(body, "capacity_head")

    if capacity_head <= 0:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "capacity_head must be > 0")

    # Check uniqueness
    for pen in store.pens.values():
        if pen["pen_code"] == pen_code:
            raise_err(ERR_DUPLICATE_PEN_CODE, "pen_code %s already in use" % pen_code)

    rec = new_record()
    rec.update({
        "pen_code": pen_code,
        "capacity_head": capacity_head,
        "status": "EMPTY",
        "current_occupancy_head": 0,
    })
    store.pens[rec["id"]] = rec
    return success_object(pen_out(rec), 201)


@bp.route("/feedlot/pens", methods=["GET"])
def list_pens():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return list_response(list(store.pens.values()), pen_out)


@bp.route("/feedlot/pens/<pen_id>", methods=["GET"])
def get_pen(pen_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.pens, pen_id, ERR_PEN_NOT_FOUND, "Pen")
    return success_object(pen_out(rec))


@bp.route("/feedlot/pens/<pen_id>", methods=["PATCH"])
def patch_pen(pen_id):
    _, role = authenticate()
    authorize(role, ["FeedyardManager"])
    rec = get_or_404(store.pens, pen_id, ERR_PEN_NOT_FOUND, "Pen")
    body = body_json()
    new_status = req_str(body, "status")

    if new_status == rec["status"]:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Pen %s already has status %s" % (pen_id, new_status))

    if new_status == "MAINTENANCE":
        pen_service.enter_maintenance(rec)
    elif new_status == "EMPTY":
        pen_service.exit_maintenance(rec)
    else:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Invalid status transition: %s -> %s" % (rec["status"], new_status))

    return success_object(pen_out(rec))


@bp.route("/feedlot/pens/<pen_id>/assignments", methods=["GET"])
def list_pen_assignments(pen_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.pens, pen_id, ERR_PEN_NOT_FOUND, "Pen")
    assignments = [pa for pa in store.pen_assignments.values() if pa["pen_id"] == pen_id]
    return list_response(assignments, pen_assignment_out)


@bp.route("/feedlot/pens/<pen_id>/feed-calls", methods=["GET"])
def list_pen_feed_calls(pen_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    get_or_404(store.pens, pen_id, ERR_PEN_NOT_FOUND, "Pen")
    calls = [fc for fc in store.feed_calls.values() if fc["pen_id"] == pen_id]
    # Sort by call_date ASC (PRD 2.3 exception)
    return list_response(calls, feed_call_out,
                         sort_key=lambda fc: (fc["call_date"], fc["created_at"]))
