"""FirstResponderWalkthrough endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_VALIDATION, ERR_WALKTHROUGH_DRILL_CONFLICT,
)
from middleware import authorized, ALL_ROLES, ROLE_OFFICER, ROLE_RESPONDER
from response import success_object
from services.core import new_record, public, apply_changes
from util import CLOCK, parse_date
from validate import get_body, reject_unknown, req_date, req_enum, req_int, req_str
from routes.helpers import check_site_fk, get_path, list_query

bp = Blueprint("walkthroughs", __name__)

AGENCIES = ["FIRE", "POLICE", "EMS"]


@bp.post("/walkthroughs")
def create_walkthrough():
    authorized([ROLE_OFFICER])
    body = get_body()
    check_site_fk(body)
    reject_unknown(body, ["site_id", "agency", "scheduled_date"])
    site_id = req_str(body, "site_id")
    agency = req_enum(body, "agency", AGENCIES)
    scheduled_date = req_date(body, "scheduled_date")

    # priority 9: whole-day exclusion vs drills in SCHEDULED / IN_PROGRESS
    for d in db["drill_events"].values():
        if (d["site_id"] == site_id and d["status"] in ("SCHEDULED", "IN_PROGRESS")
                and d["scheduled_date"] == scheduled_date):
            raise_error(ERR_WALKTHROUGH_DRILL_CONFLICT,
                        "walkthrough may not share a calendar date with an active drill")

    rec = new_record("walkthroughs", {
        "site_id": site_id,
        "agency": agency,
        "scheduled_date": scheduled_date,
        "completed_date": None,
        "findings_summary": None,
        "recommendations_count": None,
        "status": "SCHEDULED",
    })
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>/walkthroughs")
def list_walkthroughs(rid):
    authorized(ALL_ROLES)
    get_path("sites", rid)
    filters = {
        "site_id": rid,
        "agency": request.args.get("agency"),
        "status": request.args.get("status"),
    }
    return list_query("walkthroughs", filters)


@bp.post("/walkthroughs/<rid>/complete")
def complete_walkthrough(rid):
    authorized([ROLE_RESPONDER])
    w = get_path("walkthroughs", rid)
    body = get_body()
    reject_unknown(body, ["completed_date", "findings_summary", "recommendations_count"])
    completed_date = req_date(body, "completed_date")
    findings = req_str(body, "findings_summary")
    rec_count = req_int(body, "recommendations_count", minimum=0)
    if parse_date(completed_date) < parse_date(w["scheduled_date"]):
        raise_error(ERR_VALIDATION, "completed_date must not precede scheduled_date")
    if parse_date(completed_date) > CLOCK.today():
        raise_error(ERR_VALIDATION, "completed_date must not be later than today")

    if w["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "walkthrough must be SCHEDULED to complete")

    apply_changes(w, {
        "status": "COMPLETED",
        "completed_date": completed_date,
        "findings_summary": findings,
        "recommendations_count": rec_count,
    })
    return success_object(public(w))
