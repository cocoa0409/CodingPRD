"""Daily checklists: create, read, list, submit, countersign (OCC + SoD + late
clearance), reject."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_RIDE_NOT_LICENSED,
    ERR_INVALID_DAY_POSTURE,
    ERR_DUPLICATE_CHECKLIST,
    ERR_CROSS_FAIR_REFERENCE,
    ERR_CHECKLIST_INVALID_STATE,
    ERR_CHECKLIST_INCOMPLETE,
    ERR_CHECKLIST_COUNTERSIGNER_CONFLICT,
    ERR_CERTIFICATION_MISSING,
    ERR_STALE_CHECKLIST_VERSION,
)
from helpers import (
    get_or_404,
    paginate,
    qparam,
    fair_id_of_checklist,
    has_valid_certification,
)
from middleware import authenticate, scope_to_fair, require_owner
from response import ok
from validators import get_body, reject_unknown, req_str, req_int

bp = Blueprint("checklists", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]


@bp.post("/daily-checklists")
def create_checklist():
    ctx = authenticate(["RideOperator"])
    body = get_body()
    reject_unknown(body, {"ride_id", "operating_day_id", "items_total"})
    ride_id = req_str(body, "ride_id")
    day_id = req_str(body, "operating_day_id")
    items_total = req_int(body, "items_total", lo=1)
    ride = db.get("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"] if ride else None)
    ride = get_or_404("rides", ride_id)
    scope_to_fair(ctx, ride["fair_id"])
    day = get_or_404("operating_days", day_id)
    if ride["license_status"] != "LICENSED":
        raise_err(ERR_RIDE_NOT_LICENSED, "Only a LICENSED ride can be checked in")
    if day["posture"] != "CHECKLIST_PHASE":
        raise_err(ERR_INVALID_DAY_POSTURE, "Checklists open during CHECKLIST_PHASE")
    # Family 8 (safety): checklist creation demands a valid operator
    # certification for the ride's class, before the family-9 duplicate check.
    if not has_valid_certification(ctx["user_id"], ride["ride_class"]):
        raise_err(ERR_CERTIFICATION_MISSING, "Caller lacks a valid certification for the ride's class")
    for existing in store["checklists"].values():
        if existing["ride_id"] == ride_id and existing["operating_day_id"] == day_id:
            raise_err(ERR_DUPLICATE_CHECKLIST, "A checklist already exists for this ride and day")
    if day["fair_id"] != ride["fair_id"]:
        raise_err(ERR_CROSS_FAIR_REFERENCE, "The operating day belongs to a different fair than the ride")
    checklist = db.register(
        "checklists",
        {
            "ride_id": ride_id,
            "operating_day_id": day_id,
            "performed_by_staff_id": ctx["user_id"],
            "countersigned_by_staff_id": None,
            "items_total": items_total,
            "items_passed": None,
            "status": "DRAFT",
            "rejection_reason": None,
        },
    )
    return ok(serialize(checklist), 201)


@bp.get("/daily-checklists/<cid>")
def get_checklist(cid):
    ctx = authenticate(ALL)
    checklist = get_or_404("checklists", cid)
    scope_to_fair(ctx, fair_id_of_checklist(checklist))
    return ok(serialize(checklist))


@bp.get("/daily-checklists")
def list_checklists():
    authenticate(ALL)
    return paginate(
        "checklists",
        {
            "ride_id": qparam("ride_id"),
            "operating_day_id": qparam("operating_day_id"),
            "performed_by_staff_id": qparam("performed_by_staff_id"),
            "countersigned_by_staff_id": qparam("countersigned_by_staff_id"),
            "status": qparam("status"),
        },
    )


@bp.post("/daily-checklists/<cid>/submit")
def submit_checklist(cid):
    ctx = authenticate(["RideOperator"])
    checklist = get_or_404("checklists", cid)
    scope_to_fair(ctx, fair_id_of_checklist(checklist))
    require_owner(ctx["user_id"] == checklist["performed_by_staff_id"])
    body = get_body()
    reject_unknown(body, {"items_passed"})
    items_passed = req_int(body, "items_passed", lo=0)
    if checklist["status"] != "DRAFT":
        raise_err(ERR_CHECKLIST_INVALID_STATE, "Only a DRAFT checklist can be submitted")
    day = db.get("operating_days", checklist["operating_day_id"])
    if day["posture"] != "CHECKLIST_PHASE":
        raise_err(ERR_INVALID_DAY_POSTURE, "Submission requires the day to be in CHECKLIST_PHASE")
    ride = db.get("rides", checklist["ride_id"])
    if not has_valid_certification(ctx["user_id"], ride["ride_class"]):
        raise_err(ERR_CERTIFICATION_MISSING, "Caller lacks a valid certification for the ride's class")
    if items_passed != checklist["items_total"]:
        raise_err(ERR_CHECKLIST_INCOMPLETE, "items_passed must equal items_total")
    checklist["items_passed"] = items_passed
    checklist["status"] = "SUBMITTED"
    touch(checklist)
    return ok(serialize(checklist))


@bp.post("/daily-checklists/<cid>/countersign")
def countersign_checklist(cid):
    ctx = authenticate(["FairManager"])
    checklist = get_or_404("checklists", cid)
    scope_to_fair(ctx, fair_id_of_checklist(checklist))
    body = get_body()
    reject_unknown(body, {"expected_checklist_version"})
    expected = req_int(body, "expected_checklist_version")
    if checklist["status"] != "SUBMITTED":
        raise_err(ERR_CHECKLIST_INVALID_STATE, "Only a SUBMITTED checklist can be countersigned")
    if expected != checklist["version"]:
        raise_err(ERR_STALE_CHECKLIST_VERSION, "expected_checklist_version does not match the checklist's current version")
    if ctx["user_id"] == checklist["performed_by_staff_id"]:
        raise_err(ERR_CHECKLIST_COUNTERSIGNER_CONFLICT, "The countersigner cannot be the performer")
    checklist["countersigned_by_staff_id"] = ctx["user_id"]
    checklist["status"] = "COUNTERSIGNED"
    touch(checklist)
    # Late clearance: reopen the ride on the spot when gates are already open.
    day = db.get("operating_days", checklist["operating_day_id"])
    ride = db.get("rides", checklist["ride_id"])
    if (
        day["posture"] == "OPEN"
        and ride["license_status"] == "LICENSED"
        and ride["daily_status"] == "CLOSED"
    ):
        ride["daily_status"] = "OPEN"
        touch(ride)
    return ok(serialize(checklist))


@bp.post("/daily-checklists/<cid>/reject")
def reject_checklist(cid):
    ctx = authenticate(["FairManager"])
    checklist = get_or_404("checklists", cid)
    scope_to_fair(ctx, fair_id_of_checklist(checklist))
    body = get_body()
    reject_unknown(body, {"reason"})
    reason = req_str(body, "reason")
    if checklist["status"] != "SUBMITTED":
        raise_err(ERR_CHECKLIST_INVALID_STATE, "Only a SUBMITTED checklist can be rejected")
    checklist["status"] = "DRAFT"
    checklist["items_passed"] = None
    checklist["countersigned_by_staff_id"] = None
    checklist["rejection_reason"] = reason
    touch(checklist)
    return ok(serialize(checklist))
