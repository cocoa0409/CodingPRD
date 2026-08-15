"""ReviewSession and ReviewVerdict endpoints (PRD §3.3, §2.12)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_SESSION_NOT_SCHEDULED,
    ERR_SESSION_NOT_OPEN,
    ERR_SESSION_NOT_CANCELLABLE,
    ERR_SESSION_NOT_READY,
    ERR_EMPTY_AGENDA,
    ERR_SOD_REVIEWER_CONFLICT,
    ERR_RATIONALE_REQUIRED,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.common import touch
from services.review import close_session
from util import new_id, now_ts, parse_dt, program_clock_iso
from validate import (
    get_body, req_str, req_enum, req_datetime, req_str_list,
    opt_str, require_path_resource, require_body_ref,
)

bp = Blueprint("sessions", __name__)

READ_ROLES = ["ProgramDirector", "ContentReviewer", "BiasSensitivityReviewer"]
VERDICT_ROLES = ["ContentReviewer", "BiasSensitivityReviewer"]
VERDICTS = ["ACCEPT", "REJECT", "REVISE"]
ROLE_FOR_KIND = {"CONTENT": "ContentReviewer", "BIAS_SENSITIVITY": "BiasSensitivityReviewer"}
OTHER_KIND = {"CONTENT": "BIAS_SENSITIVITY", "BIAS_SENSITIVITY": "CONTENT"}


@bp.post("/api/review-sessions")
def create_session():
    caller = authorized(["ProgramDirector"])
    body = get_body()
    committee_id = req_str(body, "committee_id")
    scheduled_at = req_datetime(body, "scheduled_at")
    agenda_item_ids = req_str_list(body, "agenda_item_ids")

    committee = require_body_ref("review_committees", committee_id, "committee_id")

    if len(agenda_item_ids) == 0 or len(agenda_item_ids) > 25:
        raise_error(ERR_SESSION_NOT_READY, "agenda_item_ids must be non-empty and hold at most 25 items")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "committee_id": committee_id,
        "program_id": committee["program_id"],
        "scheduled_at": scheduled_at,
        "started_at": None,
        "closed_at": None,
        "status": "SCHEDULED",
        "agenda_item_ids": agenda_item_ids,
        "_scheduled_dt": parse_dt(scheduled_at),
        "_seq": next_seq(),
    }
    db["review_sessions"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/review-sessions")
def list_sessions():
    authorized(READ_ROLES)
    filters = {
        "committee_id": request.args.get("committee_id"),
        "program_id": request.args.get("program_id"),
    }
    return list_response("review_sessions", filters)


@bp.get("/api/review-sessions/<sid>")
def get_session(sid):
    authorized(READ_ROLES)
    rec = require_path_resource("review_sessions", sid)
    return get_one(rec)


def _program_of(rec):
    return db["assessment_programs"].get(rec["program_id"])


@bp.post("/api/review-sessions/<sid>/open")
def open_session(sid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("review_sessions", sid)
    get_body()
    if rec["status"] != "SCHEDULED":
        raise_error(ERR_SESSION_NOT_SCHEDULED, "session must be SCHEDULED to open")
    program = _program_of(rec)
    if program["_clock_dt"] < rec["_scheduled_dt"]:
        raise_error(ERR_SESSION_NOT_READY, "session scheduled_at is still in the future")
    if not rec["agenda_item_ids"]:
        raise_error(ERR_EMPTY_AGENDA, "agenda_item_ids must be non-empty to open")
    rec["status"] = "OPEN"
    rec["started_at"] = program_clock_iso(program)
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/review-sessions/<sid>/close")
def close(sid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("review_sessions", sid)
    get_body()
    if rec["status"] != "OPEN":
        raise_error(ERR_SESSION_NOT_OPEN, "session must be OPEN to close")
    program = _program_of(rec)
    committee = db["review_committees"].get(rec["committee_id"])
    close_session(rec, program, committee)
    return success_object(public(rec))


@bp.post("/api/review-sessions/<sid>/cancel")
def cancel(sid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("review_sessions", sid)
    get_body()
    if rec["status"] not in ("SCHEDULED", "OPEN"):
        raise_error(ERR_SESSION_NOT_CANCELLABLE, "session is already terminal")
    if rec["status"] == "OPEN":
        for v in db["review_verdicts"].values():
            if v["session_id"] == rec["id"] and not v["soft_deleted"]:
                v["soft_deleted"] = True
                touch(v)
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/review-sessions/<sid>/verdicts")
def submit_verdict(sid):
    caller = authorized(VERDICT_ROLES)
    session = require_path_resource("review_sessions", sid)
    body = get_body()
    item_id = req_str(body, "item_id")
    verdict = req_enum(body, "verdict", VERDICTS)
    rationale = opt_str(body, "rationale")

    if session["status"] != "OPEN":
        from errors import ERR_INVALID_STATE
        raise_error(ERR_INVALID_STATE, "verdicts may only be cast while the session is OPEN")

    committee = db["review_committees"].get(session["committee_id"])
    if committee is not None and ROLE_FOR_KIND.get(committee["committee_kind"]) != caller.role:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"{caller.role} may not cast verdicts in a {committee['committee_kind']} session",
        )

    item = require_body_ref("items", item_id, "item_id")
    if item_id not in session["agenda_item_ids"]:
        raise_error(ERR_INVALID_REQUEST, "item_id is not on the session agenda")

    # Segregation of duties (§2.12): same user may not judge the same item in both
    # committee kinds within one revision cycle (bounded by returns to DRAFT).
    if committee is not None:
        other_kind = OTHER_KIND[committee["committee_kind"]]
        other_committee_ids = {
            c["id"] for c in db["review_committees"].values() if c["committee_kind"] == other_kind
        }
        for v in db["review_verdicts"].values():
            if v["reviewer_user_id"] != caller.user_id or v["item_id"] != item_id or v["soft_deleted"]:
                continue
            other_session = db["review_sessions"].get(v["session_id"])
            if other_session is None or other_session["committee_id"] not in other_committee_ids:
                continue
            if v.get("_cycle") == item["revision_cycle_count"]:
                raise_error(
                    ERR_SOD_REVIEWER_CONFLICT,
                    "same reviewer may not judge the same item in both CONTENT and BIAS_SENSITIVITY sessions within one revision cycle",
                )

    if verdict in ("REJECT", "REVISE"):
        if rationale is None or len(rationale) < 20:
            raise_error(ERR_RATIONALE_REQUIRED, "rationale of at least 20 characters is required for REJECT/REVISE verdicts")

    now = now_ts()
    program = _program_of(session)
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "session_id": session["id"],
        "item_id": item_id,
        "reviewer_user_id": caller.user_id,
        "verdict": verdict,
        "rationale": rationale,
        "submitted_at": program_clock_iso(program),
        "soft_deleted": False,
        "_cycle": item["revision_cycle_count"],
        "_seq": next_seq(),
    }
    db["review_verdicts"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/review-verdicts")
def list_verdicts():
    authorized(READ_ROLES)
    filters = {
        "session_id": request.args.get("session_id"),
        "item_id": request.args.get("item_id"),
    }
    return list_response("review_verdicts", filters)


@bp.get("/api/review-verdicts/<vid>")
def get_verdict(vid):
    authorized(READ_ROLES)
    rec = require_path_resource("review_verdicts", vid)
    return get_one(rec)
