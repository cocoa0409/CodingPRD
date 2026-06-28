"""Session lifecycle and intake. PRD §3.1, §3.4."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, recompute, intake
from services.store import base_fields, require, touch, paginate

bp = Blueprint("sessions", __name__)


def _check_session_version(session, body):
    if "expected_session_version" not in body or body.get("expected_session_version") is None:
        raise validate.bad_request("expected_session_version is required.")
    expected = body.get("expected_session_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise validate.bad_request("expected_session_version must be an integer.")
    if expected != session["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "Session version is stale.")


@bp.route("/camps/<cid>/sessions", methods=["POST"])
def create_session(cid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    camp = require(db.camps, cid)
    body = get_json_body()

    name = validate.require_str(body, "name")
    starts_on = validate.require_datetime(body, "starts_on")
    ends_on = validate.require_datetime(body, "ends_on")
    visiting_day_on = validate.require_datetime(body, "visiting_day_on")
    capacity = validate.require_int(body, "capacity")
    if capacity < 0:
        raise validate.bad_request("capacity must be non-negative.")

    # ends_on strictly after starts_on -> ERR_INVALID_REQUEST (PRD §3.1)
    if not (ends_on > starts_on):
        raise validate.bad_request("ends_on must be strictly after starts_on.")
    # visiting_day_on within [starts_on, ends_on] -> ERR_VISITING_DAY_OUT_OF_RANGE
    if visiting_day_on < starts_on or visiting_day_on > ends_on:
        raise ApiError(errors.ERR_VISITING_DAY_OUT_OF_RANGE, 422,
                       "visiting_day_on must be within the session window.")

    s = base_fields()
    s.update({
        "camp_id": camp["id"],
        "name": name,
        "starts_on_dt": starts_on,
        "ends_on_dt": ends_on,
        "visiting_day_on_dt": visiting_day_on,
        "enrollment_open": True,
        "capacity": capacity,
        "ratio_posture": "UNDERSTAFFED",
        "status": "PLANNING",
    })
    db.sessions[s["id"]] = s
    return response.success(serialize.session(s), 201)


@bp.route("/camps/<cid>/sessions", methods=["GET"])
def list_sessions(cid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    require(db.camps, cid)
    limit, offset = parse_pagination()

    status_f = request.args.get("status")
    camp_id_f = request.args.get("camp_id")

    items = [s for s in db.sessions.values() if s["camp_id"] == cid]
    if camp_id_f is not None:
        items = [s for s in items if s["camp_id"] == camp_id_f]
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.session(s) for s in page], limit, offset, total)


@bp.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    s = require(db.sessions, sid)
    return response.success(serialize.session(s), 200)


@bp.route("/sessions/<sid>/open-enrollment", methods=["POST"])
def open_enrollment(sid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    s = require(db.sessions, sid)
    body = get_json_body()

    if s["status"] != "PLANNING":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Session is not in PLANNING.")
    # at least one cabin (ERR_NO_CABINS) — a state check within this transition
    has_cabin = any(c["session_id"] == s["id"] for c in db.cabins.values())
    if not has_cabin:
        raise ApiError(errors.ERR_NO_CABINS, 409, "Session has no cabins.")
    _check_session_version(s, body)

    s["status"] = "ENROLLING"
    s["enrollment_open"] = True
    touch(s)
    return response.success(serialize.session(s), 200)


@bp.route("/sessions/<sid>/start", methods=["POST"])
def start_session(sid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    s = require(db.sessions, sid)
    body = get_json_body()

    if s["status"] != "ENROLLING":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Session is not in ENROLLING.")
    if db.now() < s["starts_on_dt"]:
        raise ApiError(errors.ERR_SESSION_NOT_STARTED, 422, "Clock has not reached starts_on.")
    recompute.recompute_session_posture(s)
    if s["ratio_posture"] != "STAFFED":
        raise ApiError(errors.ERR_SESSION_UNDERSTAFFED, 422, "Session is not fully staffed.")
    _check_session_version(s, body)

    s["status"] = "RUNNING"
    s["enrollment_open"] = False

    # all WAITLISTED applications -> WITHDRAWN (each sets REFUND_DUE only if
    # deposit_paid_cents > 0; waitlisted never have a deposit). (PRD §3.1)
    for app in db.applications.values():
        if app["session_id"] != s["id"]:
            continue
        if app["enroll_status"] == "WAITLISTED":
            app["enroll_status"] = "WITHDRAWN"
            if app["deposit_paid_cents"] > 0:
                app["payment_status"] = "REFUND_DUE"
            app["offer_expires_at_dt"] = None
            touch(app)

    touch(s)
    return response.success(serialize.session(s), 200)


@bp.route("/sessions/<sid>/close", methods=["POST"])
def close_session(sid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    s = require(db.sessions, sid)
    body = get_json_body()

    if s["status"] != "RUNNING":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Session is not in RUNNING.")
    if db.now() < s["ends_on_dt"]:
        raise ApiError(errors.ERR_SESSION_NOT_ENDED, 422, "Clock has not reached ends_on.")
    _check_session_version(s, body)

    s["status"] = "CLOSED"
    # ENROLLED applications remain ENROLLED; no refunds (PRD §3.1)
    touch(s)
    return response.success(serialize.session(s), 200)


@bp.route("/sessions/<sid>/run-intake", methods=["POST"])
def run_intake_endpoint(sid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    s = require(db.sessions, sid)
    camp = db.camps[s["camp_id"]]
    intake.run_intake(s, camp)
    return response.success(serialize.session(s), 200)
