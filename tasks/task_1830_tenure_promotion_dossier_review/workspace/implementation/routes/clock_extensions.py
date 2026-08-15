"""ClockExtensionRequest endpoints (PRD §3.3) — stop-the-clock process."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_CLOCK_EXTENSION_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_CASE_STAGE_FORBIDDEN,
    ERR_INVALID_EXTENSION_STATE,
    ERR_INVALID_INTERVAL,
    ERR_EXTENSION_INTERVAL_OVERLAP,
    ERR_EXTENSION_CAP_EXCEEDED,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calculations as calc
from services.core import new_record, touch, recompute_case_clock
from util import parse_dt, dt_to_date, is_valid_dt, clock_stamp
from validate import (
    get_body, req_str, req_enum, req_datetime_str, require_path, raw_str,
)

bp = Blueprint("clock_extensions", __name__)

REASONS = {"PARENTAL_LEAVE", "MEDICAL_LEAVE", "BEREAVEMENT", "OTHER"}

# Extension requests require a pre-DECIDED stage (PRD §3.3).
PRE_DECISION_STAGES = {
    "DOSSIER_ASSEMBLY",
    "EXTERNAL_REVIEW",
    "RETURNED_FOR_REVISION",
    "DEPT_COMMITTEE",
    "COLLEGE_COMMITTEE",
    "UNIVERSITY_COMMITTEE",
    "PROVOST_REVIEW",
}


@bp.post("/clock-extensions")
def create_extension():
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
    # Priority 6: pre-decision stage gate.
    if case is not None and case["stage"] not in PRE_DECISION_STAGES:
        raise_error(ERR_CASE_STAGE_FORBIDDEN,
                    "clock-extension requests require a pre-DECIDED stage")
    # Priority 9: interval sanity (listed before shape failures).
    is_raw = raw_str(body, "interval_start")
    ie_raw = raw_str(body, "interval_end")
    if is_raw is not None and ie_raw is not None and is_valid_dt(is_raw) and is_valid_dt(ie_raw):
        if not (parse_dt(is_raw) < parse_dt(ie_raw)):
            raise_error(ERR_INVALID_INTERVAL, "interval_start must be strictly before interval_end")
    reason = req_enum(body, "reason", REASONS)
    req_str(body, "case_id")
    interval_start = req_datetime_str(body, "interval_start")
    interval_end = req_datetime_str(body, "interval_end")
    rec = new_record("clock_extensions", {
        "case_id": case["id"] if case is not None else body.get("case_id"),
        "reason": reason,
        "interval_start": interval_start,
        "interval_end": interval_end,
        "status": "PENDING",
        "decided_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/clock-extensions")
def list_extensions():
    return list_response("clock_extensions", {
        "case_id": request.args.get("case_id"),
        "status": request.args.get("status"),
    })


@bp.get("/clock-extensions/<rid>")
def get_extension(rid):
    return get_one("clock_extensions", rid, ERR_CLOCK_EXTENSION_NOT_FOUND)


@bp.post("/clock-extensions/<rid>/approve")
def approve_extension(rid):
    authorized(["ProvostOfficer"])
    ext = require_path("clock_extensions", rid, ERR_CLOCK_EXTENSION_NOT_FOUND)
    if ext["status"] != "PENDING":
        raise_error(ERR_INVALID_EXTENSION_STATE,
                    f"cannot approve a request in status {ext['status']}")
    start_d = dt_to_date(parse_dt(ext["interval_start"]))
    end_d = dt_to_date(parse_dt(ext["interval_end"]))
    # Half-open overlap against APPROVED intervals (touching permitted).
    if calc.extension_overlaps_approved(ext["case_id"], start_d, end_d):
        raise_error(ERR_EXTENSION_INTERVAL_OVERLAP,
                    "interval overlaps an APPROVED extension")
    approved = [
        calc_interval(e) for e in db["clock_extensions"].values()
        if e["case_id"] == ext["case_id"] and e["status"] == "APPROVED"
    ]
    if calc.merged_union_days(approved + [(start_d, end_d)]) > calc.MAX_EXTENSION_DAYS:
        raise_error(ERR_EXTENSION_CAP_EXCEEDED,
                    "merged extension days would exceed 730")
    ext["status"] = "APPROVED"
    ext["decided_at"] = clock_stamp()
    touch(ext)
    case = db["cases"].get(ext["case_id"])
    if case is not None:
        recompute_case_clock(case)
        touch(case)
    return success_object(public(ext))


def calc_interval(e):
    return dt_to_date(parse_dt(e["interval_start"])), dt_to_date(parse_dt(e["interval_end"]))


@bp.post("/clock-extensions/<rid>/deny")
def deny_extension(rid):
    authorized(["ProvostOfficer"])
    ext = require_path("clock_extensions", rid, ERR_CLOCK_EXTENSION_NOT_FOUND)
    if ext["status"] != "PENDING":
        raise_error(ERR_INVALID_EXTENSION_STATE,
                    f"cannot deny a request in status {ext['status']}")
    ext["status"] = "DENIED"
    ext["decided_at"] = clock_stamp()
    touch(ext)
    return success_object(public(ext))


@bp.post("/clock-extensions/<rid>/rescind")
def rescind_extension(rid):
    authorized(["ProvostOfficer"])
    ext = require_path("clock_extensions", rid, ERR_CLOCK_EXTENSION_NOT_FOUND)
    if ext["status"] != "APPROVED":
        raise_error(ERR_INVALID_EXTENSION_STATE,
                    f"cannot rescind a request in status {ext['status']}")
    ext["status"] = "RESCINDED"
    ext["decided_at"] = clock_stamp()
    touch(ext)
    case = db["cases"].get(ext["case_id"])
    if case is not None:
        recompute_case_clock(case)
        touch(case)
    return success_object(public(ext))
