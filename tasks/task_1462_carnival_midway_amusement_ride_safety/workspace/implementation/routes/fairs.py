"""Fairs: register, read, list, request-permit, begin-teardown, archive."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_FAIR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_NO_VERIFIED_RIDES,
    ERR_DAYS_STILL_ACTIVE,
    ERR_RIDES_NOT_DISMANTLED,
)
from helpers import get_or_404, paginate, qparam
from middleware import authenticate, scope_to_fair
from response import ok
from services.calculations import permit_fee
from validators import get_body, reject_unknown, req_str, req_int, req_date

bp = Blueprint("fairs", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

FAIR_FIELDS = {
    "name",
    "operator_company_name",
    "location",
    "setup_start_date",
    "opening_date",
    "closing_date",
    "teardown_end_date",
    "midway_capacity",
}


@bp.post("/fairs")
def create_fair():
    authenticate(["StateProgramAdmin"])
    body = get_body()
    reject_unknown(body, FAIR_FIELDS)
    name = req_str(body, "name")
    operator = req_str(body, "operator_company_name")
    location = req_str(body, "location")
    setup_start = req_date(body, "setup_start_date")
    opening = req_date(body, "opening_date")
    closing = req_date(body, "closing_date")
    teardown_end = req_date(body, "teardown_end_date")
    capacity = req_int(body, "midway_capacity", lo=1)
    if not (setup_start <= opening <= closing <= teardown_end):
        raise_err(
            ERR_INVALID_REQUEST,
            "Fair dates must satisfy setup_start_date <= opening_date <= closing_date <= teardown_end_date",
        )
    fair = db.register(
        "fairs",
        {
            "name": name,
            "operator_company_name": operator,
            "location": location,
            "setup_start_date": body["setup_start_date"],
            "opening_date": body["opening_date"],
            "closing_date": body["closing_date"],
            "teardown_end_date": body["teardown_end_date"],
            "midway_capacity": capacity,
            "status": "SETUP",
        },
    )
    return ok(serialize(fair), 201)


@bp.get("/fairs/<fid>")
def get_fair(fid):
    ctx = authenticate(ALL)
    fair = get_or_404("fairs", fid)
    scope_to_fair(ctx, fair["id"])
    return ok(serialize(fair))


@bp.get("/fairs")
def list_fairs():
    authenticate(ALL)
    return paginate("fairs", {"status": qparam("status")})


@bp.post("/fairs/<fid>/request-permit")
def request_permit(fid):
    ctx = authenticate(["FairManager"])
    fair = get_or_404("fairs", fid)
    scope_to_fair(ctx, fair["id"])
    body = get_body()
    reject_unknown(body, set())
    if fair["status"] != "SETUP":
        raise_err(ERR_FAIR_INVALID_STATE, "Permit can only be requested from SETUP")
    verified = [
        r
        for r in store["rides"].values()
        if r["fair_id"] == fid and r["setup_status"] == "SETUP_VERIFIED"
    ]
    if not verified:
        raise_err(ERR_NO_VERIFIED_RIDES, "At least one SETUP_VERIFIED ride is required")
    estimated_fee, _ = permit_fee(fid, failures=0)
    permit = db.register(
        "permits",
        {
            "fair_id": fid,
            "status": "PENDING",
            "estimated_fee_cents": estimated_fee,
            "final_fee_cents": None,
            "billable_ride_count": None,
            "reinspection_failure_count": None,
            "approved_by_inspector_id": None,
            "denial_reason": None,
            "decided_at": None,
        },
    )
    fair["status"] = "PERMIT_REQUESTED"
    touch(fair)
    return ok(serialize(permit), 201)


@bp.post("/fairs/<fid>/begin-teardown")
def begin_teardown(fid):
    ctx = authenticate(["FairManager"])
    fair = get_or_404("fairs", fid)
    scope_to_fair(ctx, fair["id"])
    body = get_body()
    reject_unknown(body, set())
    if fair["status"] != "PERMITTED":
        raise_err(ERR_FAIR_INVALID_STATE, "Teardown can only begin from PERMITTED")
    if not (db.today_date() > _d(fair["closing_date"])):
        raise_err(ERR_INVALID_REQUEST, "Teardown cannot begin before the season has ended")
    for day in store["operating_days"].values():
        if day["fair_id"] == fid and day["posture"] in (
            "CHECKLIST_PHASE",
            "OPEN",
            "WEATHER_HOLD",
            "CLOSED",
        ):
            raise_err(ERR_DAYS_STILL_ACTIVE, "An operating day is still active")
    fair["status"] = "TEARDOWN"
    touch(fair)
    return ok(serialize(fair))


@bp.post("/fairs/<fid>/archive")
def archive_fair(fid):
    ctx = authenticate(["FairManager"])
    fair = get_or_404("fairs", fid)
    scope_to_fair(ctx, fair["id"])
    body = get_body()
    reject_unknown(body, set())
    if fair["status"] != "TEARDOWN":
        raise_err(ERR_FAIR_INVALID_STATE, "Only a TEARDOWN fair can be archived")
    for ride in store["rides"].values():
        if ride["fair_id"] == fid and ride["setup_status"] != "DISMANTLED":
            raise_err(ERR_RIDES_NOT_DISMANTLED, "Every ride must be DISMANTLED before archival")
    fair["status"] = "ARCHIVED"
    touch(fair)
    return ok(serialize(fair))


def _d(s):
    from datetime import datetime

    return datetime.strptime(s, "%Y-%m-%d").date()
