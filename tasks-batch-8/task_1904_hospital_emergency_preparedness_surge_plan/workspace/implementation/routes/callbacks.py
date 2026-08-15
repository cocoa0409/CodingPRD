"""Staffing call-back requests: explicit and auto-select creation, respond, cancel."""

from datetime import timedelta

from flask import Blueprint, g, request

from db import clock, store
from domain import (CALLBACK_OUTCOMES, DEPARTMENTS, get_or_404, list_response,
                    ser_callback)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_enum, field_int, field_str, new_entity, require_body, touch

bp = Blueprint("callbacks", __name__)


def _has_open_request(staff_member_id, incident_id):
    return any(
        cb["staff_member_id"] == staff_member_id
        and cb["incident_id"] == incident_id
        and cb["status"] in ("PENDING", "ACCEPTED")
        for cb in store["callback_requests"].values()
    )


def _make_request(incident_id, staff_member_id, response_window_hours):
    cb = new_entity()
    cb.update({
        "incident_id": incident_id,
        "staff_member_id": staff_member_id,
        "response_window_hours": response_window_hours,
        "status": "PENDING",
        "expires_at": cb["created_at"] + timedelta(hours=response_window_hours),
        "responded_at": None,
    })
    store["callback_requests"][cb["id"]] = cb
    return cb


@bp.post("/callback-requests")
@authorize(["PlanningChief"])
def create_callback():
    body = require_body()
    incident_id = field_str(body, "incident_id", required=True)
    staff_member_id = field_str(body, "staff_member_id")
    has_explicit = staff_member_id is not None
    has_auto = body.get("auto_select_count") is not None
    auto_select_count = field_int(body, "auto_select_count", minimum=1)
    required_department = field_enum(body, "required_department", DEPARTMENTS)
    response_window_hours = field_int(body, "response_window_hours", default=2)

    if has_explicit == has_auto:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "carry exactly one of staff_member_id or auto_select_count")

    incident = get_or_404("incidents", incident_id)
    staff = None
    if has_explicit:
        staff = get_or_404("staff_members", staff_member_id)

    if incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "call-back requests require an ACTIVATED incident")

    created = []
    if has_explicit:
        if not staff["is_active"] or not staff["callback_eligible"]:
            raise ApiError("ERR_STAFF_NOT_CALLBACK_ELIGIBLE", 422,
                           "staff member is not active and call-back eligible")
        if _has_open_request(staff_member_id, incident_id):
            raise ApiError("ERR_DUPLICATE_CALLBACK", 409,
                           "staff member already has a PENDING or ACCEPTED request "
                           "for this incident")
        created.append(_make_request(incident_id, staff_member_id,
                                     response_window_hours))
    else:
        pool = []
        for member in store["staff_members"].values():
            if not member["is_active"] or not member["callback_eligible"]:
                continue
            if required_department is not None and member["department"] != required_department:
                continue
            if _has_open_request(member["id"], incident_id):
                continue
            pool.append(member)
        # Rank: seniority score DESC, created_at ASC, badge_number ASC.
        pool.sort(key=lambda m: (-m["callback_seniority_score"],
                                 m["created_at"],
                                 m["badge_number"]))
        if len(pool) < auto_select_count:
            raise ApiError("ERR_INSUFFICIENT_CALLBACK_POOL", 422,
                           "eligible call-back pool is smaller than auto_select_count")
        for member in pool[:auto_select_count]:
            created.append(_make_request(incident_id, member["id"],
                                         response_window_hours))

    return success([ser_callback(cb) for cb in created], "array", 201)


@bp.get("/callback-requests")
@authorize(ALL_ROLES)
def list_callbacks():
    incident_id = request.args.get("incident_id")
    staff_member_id = request.args.get("staff_member_id")
    status = request.args.get("status")

    def predicate(cb):
        if incident_id is not None and cb["incident_id"] != incident_id:
            return False
        if staff_member_id is not None and cb["staff_member_id"] != staff_member_id:
            return False
        if status is not None and cb["status"] != status:
            return False
        return True

    return list_response("callback_requests", ser_callback, predicate)


@bp.get("/callback-requests/<callback_id>")
@authorize(ALL_ROLES)
def get_callback(callback_id):
    return success(ser_callback(get_or_404("callback_requests", callback_id)),
                   "object", 200)


@bp.post("/callback-requests/<callback_id>/respond")
@authorize(["OnCallStaff"])
def respond_callback(callback_id):
    cb = get_or_404("callback_requests", callback_id)
    body = require_body()
    outcome = field_enum(body, "outcome", CALLBACK_OUTCOMES, required=True)

    # Ownership rule (priority 6) precedes the state guard (priority 8).
    if g.user_id != cb["staff_member_id"]:
        raise ApiError("ERR_NOT_CALLBACK_OWNER", 403,
                       "only the addressed staff member may respond to this request")
    if cb["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a PENDING call-back request can be responded to")

    cb["status"] = "ACCEPTED" if outcome == "ACCEPT" else "DECLINED"
    cb["responded_at"] = clock.now()
    touch(cb)
    return success(ser_callback(cb), "object", 200)


@bp.post("/callback-requests/<callback_id>/cancel")
@authorize(["PlanningChief"])
def cancel_callback(callback_id):
    cb = get_or_404("callback_requests", callback_id)
    if cb["status"] not in ("PENDING", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a PENDING or ACCEPTED call-back request can be cancelled")
    cb["status"] = "CANCELLED"
    touch(cb)
    return success(ser_callback(cb), "object", 200)
