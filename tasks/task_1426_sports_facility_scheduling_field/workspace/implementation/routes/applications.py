"""Permit application routes: submit, list, read, withdraw, request-info, respond
(PRD 3.4)."""

from flask import Blueprint, request

import errors
import util
import clock
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("applications", __name__)

EVENT_TYPES = ("LEAGUE_GAME", "LEAGUE_PRACTICE", "TOURNAMENT", "SPECIAL_EVENT")


@bp.post("/permit-applications")
def create_application():
    user_id, _ = require_roles("OrgCoordinator")
    body = util.get_json_body()
    window_id = util.require_str(body, "window_id")
    facility_id = util.require_str(body, "facility_id")
    event_date = util.require_date(body, "event_date")
    start_minute = util.require_int(body, "start_minute", min_v=0, max_v=1439)
    end_minute = util.require_int(body, "end_minute", min_v=1, max_v=1440)
    event_type = util.require_enum(body, "event_type", EVENT_TYPES)
    wants_lights = util.optional_bool(body, "wants_lights", default=False)
    headcount = util.require_int(body, "headcount", min_v=1)

    window = core.get_window(window_id)
    facility = core.get_facility(facility_id)

    # Priority 8: facility safety gate.
    if facility["condition_status"] == "CLOSED":
        raise errors.ApiError(errors.ERR_FACILITY_CLOSED,
                              "Facility condition_status is CLOSED", 409)
    if headcount > facility["capacity"]:
        raise errors.ApiError(errors.ERR_HEADCOUNT_EXCEEDS_CAPACITY,
                              "headcount exceeds facility capacity", 409)

    # Priority 9: temporal gates.
    if window["status"] != "OPEN":
        raise errors.ApiError(errors.ERR_WINDOW_NOT_OPEN,
                              "Allocation window is not OPEN", 409)
    slot_start = util.slot_datetime(event_date, start_minute)
    if slot_start <= clock.now():
        raise errors.ApiError(errors.ERR_SLOT_IN_PAST,
                              "Requested slot starts at or before the current logical clock", 409)

    # Priority 10: duration bounds.
    duration = end_minute - start_minute
    if end_minute <= start_minute or duration < 30 or duration > 480:
        raise errors.ApiError(errors.ERR_INVALID_TIME_RANGE,
                              "end_minute must exceed start_minute with duration 30..480", 409)

    org = core.get_organization(user_id)
    provisional = core.compute_score(org, event_type, window["season_code"])

    app = util.new_entity({
        "window_id": window["id"],
        "organization_id": org["id"],
        "facility_id": facility["id"],
        "event_date": event_date.strftime("%Y-%m-%d"),
        "start_minute": start_minute,
        "end_minute": end_minute,
        "event_type": event_type,
        "wants_lights": wants_lights,
        "headcount": headcount,
        "status": "SUBMITTED",
        "provisional_score": provisional,
        "final_score": None,
        "decision_note": "",
    })
    store.permit_applications[app["id"]] = app
    return success_object(app, 201)


@bp.get("/permit-applications")
def list_applications():
    require_roles(*ANY_ROLE)
    items = list(store.permit_applications.values())
    for param in ("window_id", "organization_id", "facility_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a.get(param) == val]
    return util.paginate(items)


@bp.get("/permit-applications/<aid>")
def get_application(aid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_application(aid))


@bp.post("/permit-applications/<aid>/withdraw")
def withdraw_application(aid):
    user_id, _ = require_roles("OrgCoordinator")
    app = core.get_application(aid)
    if user_id != app["organization_id"]:
        raise errors.forbidden_org()
    if app["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "WAITLISTED"):
        raise errors.ApiError(errors.ERR_INVALID_APPLICATION_STATE,
                              "Application cannot be withdrawn from its current state", 409)
    app["status"] = "WITHDRAWN"
    util.touch(app)
    return success_object(app)


@bp.post("/permit-applications/<aid>/request-info")
def request_info(aid):
    require_roles("AthleticsAdmin")
    app = core.get_application(aid)
    body = util.get_json_body()
    note = util.require_str(body, "note")
    if app["status"] != "UNDER_REVIEW":
        raise errors.ApiError(errors.ERR_INVALID_APPLICATION_STATE,
                              "Application must be UNDER_REVIEW to request info", 409)
    window = core.get_window(app["window_id"])
    if window["status"] != "CLOSED":
        raise errors.ApiError(errors.ERR_INVALID_WINDOW_STATE,
                              "Parent window must be CLOSED to request info", 409)
    app["status"] = "NEEDS_INFO"
    app["decision_note"] = note
    util.touch(app)
    return success_object(app)


@bp.post("/permit-applications/<aid>/respond")
def respond(aid):
    user_id, _ = require_roles("OrgCoordinator")
    body = util.get_json_body()
    util.require_str(body, "response_note")
    app = core.get_application(aid)
    if user_id != app["organization_id"]:
        raise errors.forbidden_org()
    if app["status"] != "NEEDS_INFO":
        raise errors.ApiError(errors.ERR_INVALID_APPLICATION_STATE,
                              "Application must be NEEDS_INFO to respond", 409)
    app["status"] = "UNDER_REVIEW"
    util.touch(app)
    return success_object(app)
