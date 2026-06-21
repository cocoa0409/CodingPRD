"""RidershipApplication endpoints (PRD §3.3, §3.4)."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import (
    err, ERR_INVALID_REFERENCE, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_NOT_ELIGIBLE, ERR_ROUTE_NOT_OPEN, ERR_ROUTE_FULL, ERR_WHEELCHAIR_FULL,
)
from services import validate as v
from services.common import (
    stamp_create, touch, parse_pagination, sorted_by_creation, paginate,
)
from services.calc import eligibility_basis
from services.domain import (
    application_public, route_assigned_rider_count, route_assigned_wheelchair_count,
)
from services.lookup import get_application
from services.notify import emit

bp = Blueprint("applications", __name__)


def _student_owner(app):
    stu = DB.students.get(app["student_id"])
    return stu["parent_id"] if stu else None


def _require_owner(p, app):
    """Parent ownership: X-User-ID must equal the application's student's parent_id."""
    if p.role == "Parent" and _student_owner(app) != p.user_id:
        raise err(ERR_FORBIDDEN, "Parent does not own this application")


def _recompute_eligibility(app):
    student = DB.students.get(app["student_id"])
    district = DB.districts.get(app["district_id"])
    basis = eligibility_basis(
        student["home_distance_miles"],
        district["walk_threshold_miles"],
        district["hazard_override_enabled"],
        student["hazard_zone"],
    )
    app["eligibility_basis"] = basis
    return basis


# ---- Submit ------------------------------------------------------------------

@bp.post("/ridership-applications")
def submit_application():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    body = v.get_body()

    district_id = v.require_str(body, "district_id")
    student_id = v.require_str(body, "student_id")
    requested_route_id = v.require_str(body, "requested_route_id")
    requested_stop_id = v.require_str(body, "requested_stop_id")

    # Body FK resolution + parentage — priority 5.
    district = DB.districts.get(district_id)
    student = DB.students.get(student_id)
    route = DB.routes.get(requested_route_id)
    stop = DB.stops.get(requested_stop_id)
    if district is None or student is None or route is None or stop is None:
        raise err(ERR_INVALID_REFERENCE, "A body reference does not resolve")
    if stop["route_id"] != requested_route_id:
        raise err(ERR_INVALID_REFERENCE, "requested_stop_id does not belong to requested_route_id")

    # Parent ownership (priority 2 / 403): a Parent may only act on their own student.
    if p.role == "Parent" and student["parent_id"] != p.user_id:
        raise err(ERR_FORBIDDEN, "Parent may only submit for their own student")

    rec = {
        "district_id": district_id,
        "student_id": student_id,
        "requested_route_id": requested_route_id,
        "requested_stop_id": requested_stop_id,
        "eligibility_basis": "PENDING",
        "status": "SUBMITTED",
        "assigned_route_id": None,
        "assigned_stop_id": None,
        "review_round": 0,
        "denial_reason": None,
    }
    stamp_create(rec)
    DB.ridership_applications[rec["id"]] = rec
    return ok(application_public(rec), 201)


@bp.get("/ridership-applications/<application_id>")
def get_application_ep(application_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    rec = get_application(application_id)
    _require_owner(p, rec)
    return ok(application_public(rec), 200)


@bp.get("/ridership-applications")
def list_applications():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    limit, offset = parse_pagination(request.args)

    records = list(DB.ridership_applications.values())

    for field in ("district_id", "student_id", "requested_route_id",
                  "requested_stop_id", "assigned_route_id", "assigned_stop_id",
                  "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]

    if p.role == "Parent":
        records = [r for r in records if _student_owner(r) == p.user_id]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([application_public(r) for r in page], limit, offset, total)


# ---- Transitions -------------------------------------------------------------

@bp.post("/ridership-applications/<application_id>/start-review")
def start_review(application_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    app = get_application(application_id)
    if app["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "start-review requires SUBMITTED")
    app["status"] = "UNDER_REVIEW"
    _recompute_eligibility(app)
    touch(app)
    return ok(application_public(app), 200)


@bp.post("/ridership-applications/<application_id>/request-changes")
def request_changes(application_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    app = get_application(application_id)
    if app["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "request-changes requires UNDER_REVIEW")
    app["status"] = "CHANGES_REQUESTED"
    touch(app)
    return ok(application_public(app), 200)


@bp.post("/ridership-applications/<application_id>/resubmit")
def resubmit(application_id):
    p = authenticate()
    require_role(p, {"Parent"})
    app = get_application(application_id)
    _require_owner(p, app)
    if app["status"] != "CHANGES_REQUESTED":
        raise err(ERR_INVALID_STATE, "resubmit requires CHANGES_REQUESTED")
    body = v.get_body()

    new_route_id = body.get("requested_route_id")
    new_stop_id = body.get("requested_stop_id")
    if new_route_id is not None or new_stop_id is not None:
        target_route = new_route_id if new_route_id is not None else app["requested_route_id"]
        target_stop = new_stop_id if new_stop_id is not None else app["requested_stop_id"]
        route = DB.routes.get(target_route)
        stop = DB.stops.get(target_stop)
        if route is None or stop is None:
            raise err(ERR_INVALID_REFERENCE, "A body reference does not resolve")
        if stop["route_id"] != target_route:
            raise err(ERR_INVALID_REFERENCE, "requested_stop_id does not belong to requested_route_id")
        app["requested_route_id"] = target_route
        app["requested_stop_id"] = target_stop

    app["status"] = "UNDER_REVIEW"
    app["review_round"] = app["review_round"] + 1
    _recompute_eligibility(app)
    touch(app)
    return ok(application_public(app), 200)


@bp.post("/ridership-applications/<application_id>/approve")
def approve(application_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    app = get_application(application_id)

    if app["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "approve requires UNDER_REVIEW")

    # Capacity gauntlet (PRD §3.4), in order.
    if app["eligibility_basis"] not in ("DISTANCE", "HAZARD"):
        raise err(ERR_NOT_ELIGIBLE, "eligibility_basis is NONE")

    route = DB.routes.get(app["requested_route_id"])
    if route["posture"] != "OPEN":
        raise err(ERR_ROUTE_NOT_OPEN, "requested route is not OPEN")

    if route_assigned_rider_count(route["id"]) >= route["seat_capacity"]:
        raise err(ERR_ROUTE_FULL, "route has no free seat")

    student = DB.students.get(app["student_id"])
    if student.get("special_needs"):
        if route_assigned_wheelchair_count(route["id"]) >= route["wheelchair_capacity"]:
            raise err(ERR_WHEELCHAIR_FULL, "route has no free securement position")

    # Commit.
    app["status"] = "APPROVED"
    app["assigned_route_id"] = app["requested_route_id"]
    app["assigned_stop_id"] = app["requested_stop_id"]
    touch(app)
    # Route counts are computed live, but the route is mutated by this approval.
    touch(route)

    emit(app["district_id"], student["parent_id"], student["id"], None,
         "APPLICATION_DECISION", {"decision": "APPROVED"})

    return ok(application_public(app), 200)


@bp.post("/ridership-applications/<application_id>/deny")
def deny(application_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    app = get_application(application_id)
    if app["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "deny requires UNDER_REVIEW")
    body = v.get_body()
    denial_reason = v.require_enum(
        body, "denial_reason",
        {"INELIGIBLE", "ROUTE_FULL", "WHEELCHAIR_FULL", "ROUTE_NOT_OPEN"})

    app["status"] = "DENIED"
    app["denial_reason"] = denial_reason
    touch(app)

    student = DB.students.get(app["student_id"])
    emit(app["district_id"], student["parent_id"], student["id"], None,
         "APPLICATION_DECISION", {"decision": "DENIED"})

    return ok(application_public(app), 200)


@bp.post("/ridership-applications/<application_id>/withdraw")
def withdraw(application_id):
    p = authenticate()
    require_role(p, {"Parent"})
    app = get_application(application_id)
    _require_owner(p, app)
    if app["status"] not in ("SUBMITTED", "CHANGES_REQUESTED"):
        raise err(ERR_INVALID_STATE, "withdraw requires SUBMITTED or CHANGES_REQUESTED")
    app["status"] = "WITHDRAWN"
    touch(app)
    return ok(application_public(app), 200)
