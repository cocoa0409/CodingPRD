"""ComplianceMeeting endpoints (PRD 3.8): annual meeting + attestation fan-out."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ATTESTATIONS_STILL_PENDING,
    ERR_DUPLICATE_MEETING_YEAR,
    ERR_MEETING_DATE_NOT_REACHED,
    ERR_MEETING_NOT_HELD,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import by_creation, new_record, public, touch
from util import add_days, clock_ts, parse_date, today
from validate import get_body, req_date, req_int, require_path_resource, soft_int

bp = Blueprint("meetings", __name__)

ATTEST_WINDOW_DAYS = 30


@bp.post("/meetings")
def create_meeting():
    authorized(["CompliancePrincipal"])
    body = get_body()
    # Priority 7: one meeting per calendar year
    year_raw = body.get("year")
    if soft_int(year_raw):
        for m in db["meetings"].values():
            if m["year"] == year_raw:
                raise_error(ERR_DUPLICATE_MEETING_YEAR,
                            "a meeting already exists for the given calendar year")
    # Priority 8: schema
    year = req_int(body, "year")
    meeting_date = req_date(body, "meeting_date")

    rec = new_record("meetings", {
        "year": year,
        "meeting_date": meeting_date,
        "held_at": None,
        "status": "SCHEDULED",
    })
    # Fan-out (meeting_attestation_fanout): every ACTIVE rep at creation time, in
    # creation order, receives a PENDING attestation due meeting_date + 30 days.
    deadline = add_days(parse_date(meeting_date), ATTEST_WINDOW_DAYS).isoformat()
    active_reps = by_creation([r for r in db["representatives"].values()
                               if r["status"] == "ACTIVE"])
    for rep in active_reps:
        new_record("attestations", {
            "meeting_id": rec["id"],
            "rep_id": rep["id"],
            "attest_deadline": deadline,
            "attested_at": None,
            "status": "PENDING",
        })
    return success_object(public(rec), status=201)


@bp.get("/meetings")
def list_meetings():
    year_raw = request.args.get("year")
    year_filter = None
    if year_raw is not None and year_raw != "":
        try:
            year_filter = int(year_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "year filter must be an integer")
    return list_response("meetings", filters={
        "year": year_filter,
        "status": request.args.get("status"),
    })


@bp.get("/meetings/<rid>")
def get_meeting(rid):
    return get_one("meetings", rid)


@bp.post("/meetings/<rid>/hold")
def hold_meeting(rid):
    authorized(["CompliancePrincipal"])
    meeting = require_path_resource("meetings", rid)
    if meeting["status"] != "SCHEDULED":
        raise_error(ERR_MEETING_NOT_HELD, "hold is allowed only from SCHEDULED")
    if today() < parse_date(meeting["meeting_date"]):
        raise_error(ERR_MEETING_DATE_NOT_REACHED,
                    "the meeting date has not been reached")
    meeting["held_at"] = clock_ts()
    meeting["status"] = "HELD"
    touch(meeting)
    return success_object(public(meeting))


@bp.post("/meetings/<rid>/close")
def close_meeting(rid):
    authorized(["CompliancePrincipal"])
    meeting = require_path_resource("meetings", rid)
    if meeting["status"] != "HELD":
        raise_error(ERR_MEETING_NOT_HELD, "close is allowed only from HELD")
    for a in db["attestations"].values():
        if a["meeting_id"] == meeting["id"] and a["status"] == "PENDING":
            raise_error(ERR_ATTESTATIONS_STILL_PENDING,
                        "every attestation must be ATTESTED or OVERDUE before closing")
    meeting["status"] = "CLOSED"
    touch(meeting)
    return success_object(public(meeting))
