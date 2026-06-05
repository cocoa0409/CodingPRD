"""Appeal filing, assignment, and decision (AFFIRM/REVERSE/REMAND)."""

from datetime import timedelta

from flask import Blueprint, g, request as flask_request

import db
import services
from clock import parse_iso
from errors import (
    api_error,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_NOT_APPEALABLE, ERR_APPEAL_WINDOW_CLOSED,
)
from helpers import (
    get_json_body, require_str, require_enum, get_or_404, fk_or_404,
    serialize, parse_pagination, sort_by_creation, paginate,
)
from middleware import require_roles
from response import ok_object, ok_array

bp = Blueprint("appeals", __name__)

DETERMINATION_STATES = {"GRANTED", "PARTIALLY_GRANTED", "DENIED", "GLOMAR_INVOKED"}
DECISIONS = {"AFFIRM", "REVERSE", "REMAND"}


# ---- File an appeal --------------------------------------------------------
@bp.post("/requests/<rid>/appeals")
def file_appeal(rid):
    require_roles("Requester")
    req = get_or_404(db.requests, rid)
    if req["requester_id"] != g.user_id:
        raise api_error(ERR_NOT_RESOURCE_OWNER, "Only the owning requester may file an appeal.")
    body = get_json_body()
    # Body-FK existence (priority 5) before remaining structural validity (6).
    appellant_id = require_str(body, "appellant_id")
    fk_or_404(db.requesters, appellant_id)
    grounds = require_str(body, "grounds")
    filed_at = require_str(body, "filed_at")
    filed_dt = parse_iso(filed_at)
    if filed_dt is None:
        raise api_error(ERR_INVALID_REQUEST, "filed_at must be a valid ISO 8601 instant.")

    if appellant_id != req["requester_id"]:
        raise api_error(ERR_INVALID_REQUEST, "appellant_id must equal the request's requester_id.")

    if req["status"] not in DETERMINATION_STATES:
        raise api_error(ERR_NOT_APPEALABLE, "Appeals require a request in a determination state.")

    det_at = req.get("_determination_at")
    if det_at is not None:
        if filed_dt > det_at + timedelta(days=services.APPEAL_WINDOW_DAYS):
            raise api_error(ERR_APPEAL_WINDOW_CLOSED, "Appeal filed more than 90 calendar days after the determination.")

    obj = {
        "request_id": rid,
        "appellant_id": appellant_id,
        "assigned_authority_id": None,
        "grounds": grounds,
        "status": "FILED",
        "filed_at": filed_at,
    }
    db.stamp_create(obj)
    db.appeals[obj["id"]] = obj
    services.append_audit(rid, "APPEAL_FILED", "appeal filed", "Requester")
    return ok_object(serialize("Appeal", obj), status=201)


@bp.get("/appeals/<aid>")
def get_appeal(aid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.appeals, aid)
    return ok_object(serialize("Appeal", obj), status=200)


@bp.get("/requests/<rid>/appeals")
def list_request_appeals(rid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    get_or_404(db.requests, rid)
    limit, offset = parse_pagination()
    items = sort_by_creation([a for a in db.appeals.values() if a["request_id"] == rid])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("Appeal", a) for a in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.get("/appeals")
def list_appeals():
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    limit, offset = parse_pagination()
    appellant_id = flask_request.args.get("appellant_id")
    assigned_authority_id = flask_request.args.get("assigned_authority_id")
    request_id = flask_request.args.get("request_id")
    items = list(db.appeals.values())
    if appellant_id is not None:
        items = [a for a in items if a["appellant_id"] == appellant_id]
    if assigned_authority_id is not None:
        items = [a for a in items if a["assigned_authority_id"] == assigned_authority_id]
    if request_id is not None:
        items = [a for a in items if a["request_id"] == request_id]
    items = sort_by_creation(items)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("Appeal", a) for a in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


# ---- Assign ----------------------------------------------------------------
@bp.post("/appeals/<aid>/assign")
def assign_appeal(aid):
    require_roles("AppealAuthority")
    appeal = get_or_404(db.appeals, aid)
    if appeal["status"] != "FILED":
        raise api_error(ERR_INVALID_STATE, "Appeal must be FILED to take it up.")
    appeal["assigned_authority_id"] = g.user_id
    appeal["status"] = "UNDER_REVIEW"
    db.touch(appeal)
    return ok_object(serialize("Appeal", appeal), status=200)


# ---- Decide ----------------------------------------------------------------
@bp.post("/appeals/<aid>/decide")
def decide_appeal(aid):
    require_roles("AppealAuthority")
    appeal = get_or_404(db.appeals, aid)
    body = get_json_body()
    decision = require_enum(body, "decision", DECISIONS)
    if appeal["status"] != "UNDER_REVIEW":
        raise api_error(ERR_INVALID_STATE, "Appeal must be UNDER_REVIEW to decide.")

    rid = appeal["request_id"]
    req = db.requests.get(rid)

    if decision == "AFFIRM":
        appeal["status"] = "AFFIRMED"
        db.touch(appeal)
        services.append_audit(rid, "APPEAL_DECIDED", "affirmed", "AppealAuthority")
    elif decision == "REVERSE":
        appeal["status"] = "REVERSED"
        db.touch(appeal)
        for rec in services.records_for_request(rid):
            rec["disposition"] = "RELEASABLE"
            db.touch(rec)
        if req is not None:
            req["status"] = "GRANTED"
            db.touch(req)
        services.append_audit(rid, "APPEAL_DECIDED", "reversed; full release", "AppealAuthority")
    else:  # REMAND
        appeal["status"] = "REMANDED"
        db.touch(appeal)
        # Cross-entity remand reset of the request and its records.
        if req is not None:
            req["status"] = "PROCESSING"
            req["deadline_status"] = "RUNNING"
            db.touch(req)
            for rec in services.records_for_request(rid):
                rec["disposition"] = "PENDING"
                db.touch(rec)
        services.append_audit(rid, "APPEAL_DECIDED", "remanded; reopened for reprocessing", "AppealAuthority")

    return ok_object(serialize("Appeal", appeal), status=200)
