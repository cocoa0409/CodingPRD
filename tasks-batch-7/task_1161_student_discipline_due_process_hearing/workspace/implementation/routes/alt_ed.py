"""Alternative-education sites and placements (PRD §3.7)."""
from flask import Blueprint, request

from db import db, stamp, touch, serialize, clock
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_MDR_INCOMPLETE,
    ERR_SITE_CAPACITY_EXCEEDED,
    ERR_PLACEMENT_ALREADY_ACTIVE,
    ERR_PLACEMENT_NOT_STARTED,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, render_list
from services.calc import seats_occupied, open_mdr_exists, completed_mdr_exists
from util import is_int, parse_dt

bp = Blueprint("alt_ed", __name__)

PLACEMENT_STATUSES = {"PLACED", "ACTIVE", "COMPLETED", "EXITED_EARLY"}


def _site_serializer(site):
    return serialize(site, extra={"seats_occupied": seats_occupied(site)})


@bp.post("/alt-ed-sites")
@endpoint("DistrictAdmin")
def create_site(ctx):
    name = ctx.body.get("name")
    capacity = ctx.body.get("capacity")
    if not isinstance(name, str) or not name:
        raise_err(ERR_INVALID_REQUEST, "name is required")
    if not is_int(capacity) or capacity < 1:
        raise_err(ERR_INVALID_REQUEST, "capacity must be an integer >= 1")
    site = stamp({"name": name, "capacity": capacity})
    db.sites[site["id"]] = site
    return success(_site_serializer(site), 201)


@bp.get("/alt-ed-sites/<sid>")
@endpoint("DistrictAdmin", "StudentServicesDirector")
def get_site(ctx, sid):
    site = get_or_404(db.sites, sid, "site")
    return success(_site_serializer(site))


@bp.post("/placements")
@endpoint("StudentServicesDirector")
def create_placement(ctx):
    b = ctx.body
    case_id = b.get("case_id")
    site_id = b.get("site_id")
    # Body-carried FK existence (rung 5), left to right: case before site
    if isinstance(case_id, str) and case_id not in db.cases:
        raise_err(ERR_NOT_FOUND, f"case not found: {case_id}")
    if isinstance(site_id, str) and site_id not in db.sites:
        raise_err(ERR_NOT_FOUND, f"site not found: {site_id}")
    if not isinstance(case_id, str):
        raise_err(ERR_INVALID_REQUEST, "case_id is required")
    if not isinstance(site_id, str):
        raise_err(ERR_INVALID_REQUEST, "site_id is required")
    start = parse_dt(b.get("start_date"))
    end = parse_dt(b.get("planned_end_date"))
    if start is None or end is None:
        raise_err(ERR_INVALID_REQUEST, "start_date and planned_end_date must be valid ISO 8601 dates")
    if end < start:
        raise_err(ERR_INVALID_REQUEST, "planned_end_date must be on or after start_date")

    case = db.cases[case_id]
    site = db.sites[site_id]
    student = db.students[case["student_id"]]
    if case["status"] != "EXPULSION_ACTIVE":
        raise_err(ERR_INVALID_STATE, "case must be EXPULSION_ACTIVE to place the student")
    # IDEA/504 safety gate (rung 9): no open MDR; disability students need a COMPLETED MDR
    if open_mdr_exists(case_id):
        raise_err(ERR_MDR_INCOMPLETE, "an open manifestation determination blocks placement")
    if student["disability_status"] != "NONE" and not completed_mdr_exists(case_id):
        raise_err(ERR_MDR_INCOMPLETE, "a COMPLETED manifestation determination is required")
    # Aggregate capacity over closed date intervals, counting the new placement
    overlapping = sum(
        1
        for p in db.placements.values()
        if p["site_id"] == site_id
        and p["status"] in ("PLACED", "ACTIVE")
        and start.date() <= p["planned_end_date"].date()
        and p["start_date"].date() <= end.date()
    )
    if overlapping + 1 > site["capacity"]:
        raise_err(ERR_SITE_CAPACITY_EXCEEDED, "site capacity exceeded for the placement interval")
    if any(
        p["case_id"] == case_id and p["status"] in ("PLACED", "ACTIVE")
        for p in db.placements.values()
    ):
        raise_err(ERR_PLACEMENT_ALREADY_ACTIVE, "case already has an open placement")

    placement = stamp(
        {
            "case_id": case_id,
            "site_id": site_id,
            "start_date": start,
            "planned_end_date": end,
            "status": "PLACED",
            "actual_end_date": None,
        }
    )
    db.placements[placement["id"]] = placement
    return success(serialize(placement), 201)


@bp.get("/placements/<pid>")
@endpoint("DistrictAdmin", "StudentServicesDirector")
def get_placement(ctx, pid):
    return success(serialize(get_or_404(db.placements, pid, "placement")))


@bp.get("/placements")
@endpoint("DistrictAdmin", "StudentServicesDirector")
def list_placements(ctx):
    case_id = request.args.get("case_id")
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if status is not None and status not in PLACEMENT_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.placements, {"case_id": case_id, "site_id": site_id, "status": status}
    )


@bp.post("/placements/<pid>/activate")
@endpoint("StudentServicesDirector")
def activate_placement(ctx, pid):
    placement = get_or_404(db.placements, pid, "placement")
    if placement["status"] != "PLACED":
        raise_err(ERR_INVALID_STATE, "placement is not PLACED")
    if clock() < placement["start_date"]:
        raise_err(ERR_PLACEMENT_NOT_STARTED, "placement has not reached its start date")
    placement["status"] = "ACTIVE"
    touch(placement)
    student = db.students[db.cases[placement["case_id"]]["student_id"]]
    student["enrollment_status"] = "IN_ALT_ED"
    touch(student)
    return success(serialize(placement))


@bp.post("/placements/<pid>/complete")
@endpoint("StudentServicesDirector")
def complete_placement(ctx, pid):
    placement = get_or_404(db.placements, pid, "placement")
    outcome = ctx.body.get("outcome")
    if outcome not in ("COMPLETED", "EXITED_EARLY"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be COMPLETED or EXITED_EARLY")
    if placement["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "placement is not ACTIVE")
    placement["status"] = outcome
    placement["actual_end_date"] = clock()
    touch(placement)
    student = db.students[db.cases[placement["case_id"]]["student_id"]]
    student["enrollment_status"] = "ENROLLED"
    touch(student)
    return success(serialize(placement))
