"""AirspaceAuthorization endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at, clock_now, parse_dt, fmt_dt
from middleware import require_role, get_auth
from response import success_object, success_list
from services import calc
from services.show import (
    serialize_authorization, touch, auth_covers_show, revoke_authorization_cascade,
)

bp = Blueprint("authorizations", __name__)


def _get_auth(auth_id):
    a = DB.authorizations.get(auth_id)
    if a is None:
        raise errors.not_found("ERR_AUTHORIZATION_NOT_FOUND", "authorization not found")
    return a


@bp.route("/api/airspace-authorizations", methods=["POST"])
def create_authorization():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_event_id", "window_start", "window_end",
                        "altitude_ceiling_ft", "waiver_types"])
    require_role("ProductionPlanner")
    show_id = body["show_event_id"]
    if not isinstance(show_id, str):
        raise errors.validation("show_event_id must be a string")
    ws_raw, ws = V.req_dt(body, "window_start")
    we_raw, we = V.req_dt(body, "window_end")
    ceil = V.req_number(body, "altitude_ceiling_ft")
    waivers = body["waiver_types"]
    if not isinstance(waivers, list) or not all(isinstance(w, str) for w in waivers):
        raise errors.validation("waiver_types must be an array of strings")
    if not (we > ws):
        raise errors.validation("window_end must be after window_start")
    if ceil <= 0:
        raise errors.validation("altitude_ceiling_ft must be > 0")

    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")

    aid = new_id()
    ts = wall_created_at()
    auth = {
        "id": aid, "show_event_id": show_id,
        "window_start": ws_raw, "window_end": we_raw,
        "altitude_ceiling_ft": ceil, "waiver_types": list(waivers),
        "status": "DRAFT", "decided_at": None, "decided_by": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.authorizations[aid] = auth
    DB.insertion_order["authorizations"].append(aid)
    return success_object(serialize_authorization(auth), 201)


@bp.route("/api/airspace-authorizations/<authorizationId>", methods=["GET"])
def get_authorization(authorizationId):
    get_auth()
    return success_object(serialize_authorization(_get_auth(authorizationId)))


@bp.route("/api/airspace-authorizations", methods=["GET"])
def list_authorizations():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    show_id = V.opt_string(request.args, "show_event_id")
    status = V.opt_string(request.args, "status")
    items = [DB.authorizations[i] for i in DB.insertion_order["authorizations"]]
    if show_id is not None:
        items = [a for a in items if a["show_event_id"] == show_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_authorization(a) for a in page], limit, offset, total)


def _regulatory_checks(auth, show, overlap_statuses):
    site = DB.sites.get(show["site_id"])
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")
    if auth["altitude_ceiling_ft"] > site["site_max_altitude_ft"]:
        raise errors.conflict("ERR_ALTITUDE_CEILING_EXCEEDS_SITE", "ceiling exceeds site max altitude")
    if not auth_covers_show(auth, show):
        raise errors.conflict("ERR_AUTHORIZATION_WINDOW_INSUFFICIENT", "window does not cover show window")
    if calc.authorization_window_overlap(
            site["id"], parse_dt(auth["window_start"]), parse_dt(auth["window_end"]),
            overlap_statuses, exclude_auth_id=auth["id"]):
        raise errors.conflict("ERR_AUTHORIZATION_WINDOW_OVERLAP", "authorization window overlaps another at the site")


@bp.route("/api/airspace-authorizations/<authorizationId>/submit", methods=["POST"])
def submit_authorization(authorizationId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("ProductionPlanner")
    auth = _get_auth(authorizationId)
    show = DB.show_events.get(auth["show_event_id"])
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")
    if auth["status"] != "DRAFT":
        raise errors.conflict("ERR_INVALID_STATE", "authorization must be DRAFT to submit")
    _regulatory_checks(auth, show, ("UNDER_REVIEW", "APPROVED"))
    auth["status"] = "UNDER_REVIEW"
    touch(auth)
    return success_object(serialize_authorization(auth))


@bp.route("/api/airspace-authorizations/<authorizationId>/request-info", methods=["POST"])
def request_info(authorizationId):
    body = V.get_body()
    V.reject_system_fields(body)
    if "info_note" in body and body["info_note"] is not None and not isinstance(body["info_note"], str):
        raise errors.validation("info_note must be a string")
    require_role("AuthorityOfficer")
    auth = _get_auth(authorizationId)
    if auth["status"] != "UNDER_REVIEW":
        raise errors.conflict("ERR_INVALID_STATE", "authorization must be UNDER_REVIEW")
    auth["status"] = "INFO_REQUESTED"
    touch(auth)
    return success_object(serialize_authorization(auth))


@bp.route("/api/airspace-authorizations/<authorizationId>/resubmit", methods=["POST"])
def resubmit(authorizationId):
    body = V.get_body()
    V.reject_system_fields(body)
    if "amendment_note" in body and body["amendment_note"] is not None and not isinstance(body["amendment_note"], str):
        raise errors.validation("amendment_note must be a string")
    require_role("ProductionPlanner")
    auth = _get_auth(authorizationId)
    if auth["status"] != "INFO_REQUESTED":
        raise errors.conflict("ERR_INVALID_STATE", "authorization must be INFO_REQUESTED")
    auth["status"] = "UNDER_REVIEW"
    touch(auth)
    return success_object(serialize_authorization(auth))


@bp.route("/api/airspace-authorizations/<authorizationId>/decide", methods=["POST"])
def decide(authorizationId):
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["decision"])
    uid, _ = require_role("AuthorityOfficer")
    decision = V.req_enum(body, "decision", {"APPROVED", "DENIED"})
    auth = _get_auth(authorizationId)
    show = DB.show_events.get(auth["show_event_id"])
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")
    if auth["status"] != "UNDER_REVIEW":
        raise errors.conflict("ERR_INVALID_STATE", "authorization must be UNDER_REVIEW to decide")
    if decision == "APPROVED":
        _regulatory_checks(auth, show, ("APPROVED",))
    auth["status"] = decision
    auth["decided_at"] = fmt_dt(clock_now())
    auth["decided_by"] = uid
    touch(auth)
    return success_object(serialize_authorization(auth))


@bp.route("/api/airspace-authorizations/<authorizationId>/revise", methods=["POST"])
def revise(authorizationId):
    body = V.get_body()
    V.reject_system_fields(body)
    # schema-validate the optional amendments before existence/auth ordering
    new_ws_pair = V.opt_dt(body, "window_start")
    new_we_pair = V.opt_dt(body, "window_end")
    new_ceil = None
    if "altitude_ceiling_ft" in body and body["altitude_ceiling_ft"] is not None:
        new_ceil = V.req_number(body, "altitude_ceiling_ft")
        if new_ceil <= 0:
            raise errors.validation("altitude_ceiling_ft must be > 0")
    if new_ws_pair is not None and new_we_pair is not None and not (new_we_pair[1] > new_ws_pair[1]):
        raise errors.validation("window_end must be after window_start")
    require_role("ProductionPlanner")
    auth = _get_auth(authorizationId)
    if auth["status"] != "DENIED":
        raise errors.conflict("ERR_INVALID_STATE", "authorization must be DENIED to revise")
    # Apply partial amendments; then validate window pairing
    ws_raw = new_ws_pair[0] if new_ws_pair is not None else auth["window_start"]
    we_raw = new_we_pair[0] if new_we_pair is not None else auth["window_end"]
    ws = new_ws_pair[1] if new_ws_pair is not None else parse_dt(auth["window_start"])
    we = new_we_pair[1] if new_we_pair is not None else parse_dt(auth["window_end"])
    if not (we > ws):
        raise errors.validation("window_end must be after window_start")
    auth["window_start"] = ws_raw
    auth["window_end"] = we_raw
    if new_ceil is not None:
        auth["altitude_ceiling_ft"] = new_ceil
    auth["status"] = "DRAFT"
    auth["decided_at"] = None
    auth["decided_by"] = None
    touch(auth)
    return success_object(serialize_authorization(auth))


@bp.route("/api/airspace-authorizations/<authorizationId>/revoke", methods=["POST"])
def revoke(authorizationId):
    body = V.get_body()
    V.reject_system_fields(body)
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        raise errors.validation("reason must be a string")
    require_role("AuthorityOfficer")
    auth = _get_auth(authorizationId)
    if auth["status"] != "APPROVED":
        raise errors.conflict("ERR_INVALID_STATE", "authorization must be APPROVED to revoke")
    auth["status"] = "REVOKED"
    touch(auth)
    revoke_authorization_cascade(auth)
    return success_object(serialize_authorization(auth))


@bp.route("/api/airspace-authorizations/<authorizationId>/withdraw", methods=["POST"])
def withdraw(authorizationId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("ProductionPlanner")
    auth = _get_auth(authorizationId)
    if auth["status"] != "DRAFT":
        raise errors.conflict("ERR_INVALID_STATE", "authorization must be DRAFT to withdraw")
    auth["status"] = "WITHDRAWN"
    touch(auth)
    return success_object(serialize_authorization(auth))
