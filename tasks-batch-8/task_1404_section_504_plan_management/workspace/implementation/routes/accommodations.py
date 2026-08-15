"""Accommodations: add, suspend, resume, discontinue (with testing-request cascade)."""
from flask import Blueprint, request

from db import db, create_record, touch
from errors import (ERR_ACCOMMODATION_NOT_ACTIVE, ERR_ACCOMMODATION_NOT_DISCONTINUABLE,
                    ERR_ACCOMMODATION_NOT_SUSPENDED, ERR_PLAN_NOT_ACTIVE, raise_err)
from middleware import body, opt_bool, req_enum, req_str, require_roles
from response import success
from routes import list_response
from services import (ACCOMMODATION_TYPES, accommodation_out, get_accommodation,
                      get_plan, posture_gate, school_of_plan)

bp = Blueprint("accommodations", __name__)

ACC_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal", "Teacher", "Parent")


@bp.post("/accommodations")
@require_roles("Section504Coordinator")
def create_accommodation():
    d = body()
    plan = get_plan(req_str(d, "plan_id"))
    posture_gate(school_of_plan(plan))
    rec = create_record(db.accommodations, {
        "plan_id": plan["id"],
        "accommodation_type": req_enum(d, "accommodation_type", ACCOMMODATION_TYPES),
        "description": req_str(d, "description"),
        "accommodation_status": "DRAFT",
        "applies_to_testing": opt_bool(d, "applies_to_testing", False),
    })
    # Adding an accommodation is a mutation of the parent plan (OCC anchor).
    touch(plan)
    return success(accommodation_out(rec), 201)


@bp.get("/accommodations")
@require_roles(*ACC_READERS)
def list_accommodations():
    items = list(db.accommodations.values())
    plan_id = request.args.get("plan_id")
    status = request.args.get("accommodation_status")
    atype = request.args.get("accommodation_type")
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if status is not None:
        items = [a for a in items if a["accommodation_status"] == status]
    if atype is not None:
        items = [a for a in items if a["accommodation_type"] == atype]
    return list_response(items, accommodation_out)


@bp.get("/accommodations/<accommodationId>")
@require_roles(*ACC_READERS)
def get_accommodation_detail(accommodationId):
    return success(accommodation_out(get_accommodation(accommodationId)), 200)


def _deny_open_testing_requests(accommodation):
    """Cascade: requests referencing this accommodation in SUBMITTED or
    PENDING_DISTRICT_REVIEW are auto-denied."""
    for t in db.testing_requests.values():
        if (t["accommodation_id"] == accommodation["id"]
                and t["request_status"] in ("SUBMITTED", "PENDING_DISTRICT_REVIEW")):
            t["request_status"] = "DENIED"
            touch(t)


@bp.post("/accommodations/<accommodationId>/suspend")
@require_roles("Section504Coordinator")
def suspend_accommodation(accommodationId):
    acc = get_accommodation(accommodationId)
    plan = get_plan(acc["plan_id"])
    posture_gate(school_of_plan(plan))
    if acc["accommodation_status"] != "ACTIVE":
        raise_err(ERR_ACCOMMODATION_NOT_ACTIVE, "Accommodation must be ACTIVE to suspend")
    if plan["plan_status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to suspend an accommodation")
    acc["accommodation_status"] = "SUSPENDED"
    touch(acc)
    return success(accommodation_out(acc), 200)


@bp.post("/accommodations/<accommodationId>/resume")
@require_roles("Section504Coordinator")
def resume_accommodation(accommodationId):
    acc = get_accommodation(accommodationId)
    plan = get_plan(acc["plan_id"])
    posture_gate(school_of_plan(plan))
    if acc["accommodation_status"] != "SUSPENDED":
        raise_err(ERR_ACCOMMODATION_NOT_SUSPENDED, "Accommodation must be SUSPENDED to resume")
    if plan["plan_status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to resume an accommodation")
    acc["accommodation_status"] = "ACTIVE"
    touch(acc)
    return success(accommodation_out(acc), 200)


@bp.post("/accommodations/<accommodationId>/discontinue")
@require_roles("Section504Coordinator")
def discontinue_accommodation(accommodationId):
    acc = get_accommodation(accommodationId)
    plan = get_plan(acc["plan_id"])
    posture_gate(school_of_plan(plan))
    if acc["accommodation_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_ACCOMMODATION_NOT_DISCONTINUABLE,
                  "Accommodation must be ACTIVE or SUSPENDED to discontinue")
    acc["accommodation_status"] = "DISCONTINUED"
    touch(acc)
    _deny_open_testing_requests(acc)
    return success(accommodation_out(acc), 200)
