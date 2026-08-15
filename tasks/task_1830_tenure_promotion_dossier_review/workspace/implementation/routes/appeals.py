"""Appeal endpoints (PRD §3.8) — filing, review, resolution, remand cascade."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_APPEAL_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_CASE_STAGE_FORBIDDEN,
    ERR_INVALID_APPEAL_STATE,
    ERR_APPEAL_WINDOW_LAPSED,
    ERR_APPEAL_ALREADY_OPEN,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch, remand_cascade
from util import CLOCK, parse_dt
from validate import get_body, req_str, req_enum, require_path, raw_str

bp = Blueprint("appeals", __name__)

GROUNDS = {"PROCEDURAL_ERROR", "NEW_EVIDENCE", "DISCRIMINATION", "CAPRICIOUS_EVALUATION"}
RESOLUTIONS = {"UPHELD", "DENIED", "REMANDED"}
OPEN_APPEAL_STATUSES = {"FILED", "UNDER_REVIEW"}


@bp.post("/appeals")
def create_appeal():
    caller = authorized(["Candidate"])
    body = get_body()
    # Priority 4: case FK existence.
    case = None
    case_id_raw = raw_str(body, "case_id")
    if case_id_raw is not None:
        case = db["cases"].get(case_id_raw)
        if case is None:
            raise_error(ERR_CASE_NOT_FOUND, "case_id does not resolve")
    # Priority 5: ownership.
    if case is not None and caller.user_id != case["candidate_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting user does not own this case")
    # Priority 6: appeals may be filed only while the case is NOTIFIED.
    if case is not None and case["stage"] != "NOTIFIED":
        raise_error(ERR_CASE_STAGE_FORBIDDEN, "appeals require the case to be NOTIFIED")
    # Priority 9: shape.
    req_str(body, "case_id")
    grounds = req_enum(body, "grounds", GROUNDS)
    # Priority 10: filing window (exactly at the deadline is permitted).
    if case is not None and case["appeal_filing_deadline"] is not None:
        if CLOCK.now() > parse_dt(case["appeal_filing_deadline"]):
            raise_error(ERR_APPEAL_WINDOW_LAPSED, "the appeal filing deadline has passed")
    # Priority 11: a single open appeal per case.
    if case is not None:
        for a in db["appeals"].values():
            if a["case_id"] == case["id"] and a["status"] in OPEN_APPEAL_STATUSES:
                raise_error(ERR_APPEAL_ALREADY_OPEN,
                            "an open appeal already exists for the case")
    rec = new_record("appeals", {
        "case_id": case["id"],
        "grounds": grounds,
        "filed_at": CLOCK.now_iso(),
        "status": "FILED",
        "resolution": None,
        "resolution_text": None,
        "resolved_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/appeals")
def list_appeals():
    return list_response("appeals", {
        "case_id": request.args.get("case_id"),
        "status": request.args.get("status"),
    })


@bp.get("/appeals/<rid>")
def get_appeal(rid):
    return get_one("appeals", rid, ERR_APPEAL_NOT_FOUND)


@bp.post("/appeals/<rid>/begin-review")
def begin_review(rid):
    authorized(["AppealOfficer"])
    appeal = require_path("appeals", rid, ERR_APPEAL_NOT_FOUND)
    if appeal["status"] != "FILED":
        raise_error(ERR_INVALID_APPEAL_STATE,
                    f"cannot begin review of an appeal in status {appeal['status']}")
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return success_object(public(appeal))


@bp.post("/appeals/<rid>/resolve")
def resolve_appeal(rid):
    authorized(["AppealOfficer"])
    appeal = require_path("appeals", rid, ERR_APPEAL_NOT_FOUND)
    if appeal["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_APPEAL_STATE,
                    f"cannot resolve an appeal in status {appeal['status']}")
    body = get_body()
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    resolution_text = req_str(body, "resolution_text")
    case = db["cases"].get(appeal["case_id"])
    if resolution == "REMANDED":
        if case is None or case["stage"] not in ("DECIDED", "NOTIFIED"):
            raise_error(ERR_CASE_STAGE_FORBIDDEN,
                        "remand requires the case to be DECIDED or NOTIFIED")
        # remand_cascade pre-checks the committee selector before mutating
        # (an empty DEPARTMENT pool fails this call with ERR_NO_ELIGIBLE_COMMITTEE).
        remand_cascade(case)
    appeal["resolution"] = resolution
    appeal["resolution_text"] = resolution_text
    appeal["resolved_at"] = CLOCK.now_iso()
    appeal["status"] = resolution
    touch(appeal)
    return success_object(public(appeal))


@bp.post("/appeals/<rid>/withdraw")
def withdraw_appeal(rid):
    caller = authorized(["Candidate"])
    appeal = require_path("appeals", rid, ERR_APPEAL_NOT_FOUND)
    case = db["cases"].get(appeal["case_id"])
    if case is None or caller.user_id != case["candidate_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting user does not own this case")
    if appeal["status"] != "FILED":
        raise_error(ERR_INVALID_APPEAL_STATE,
                    f"cannot withdraw an appeal in status {appeal['status']}")
    appeal["status"] = "WITHDRAWN"
    touch(appeal)
    return success_object(public(appeal))
