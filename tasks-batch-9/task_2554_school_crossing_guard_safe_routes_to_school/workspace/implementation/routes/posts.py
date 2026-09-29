"""Guard posts and dated staffing assignments (PRD 3.5)."""
from flask import Blueprint

import calc
import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from errors import bad_request, fail
from response import list_response, object_response
from timeutil import add_days, fmt_date, fmt_dt, parse_date

bp = Blueprint("posts", __name__)

SHIFTS = ("AM", "PM", "BOTH")
POST_READ_ROLES = ("ProgramAdmin", "TrafficEngineer", "CrossingSupervisor", "SchoolLiaison")
ASSIGNMENT_READ_ROLES = ("ProgramAdmin", "CrossingSupervisor", "CrossingGuard")


@bp.post("/srts/guard-posts")
def propose_post():
    require("CrossingSupervisor", "ProgramAdmin")
    body = v.body()
    intersection_id = v.req_str(body, "intersection_id")
    post_label = v.req_str(body, "post_label")
    zone_code = v.req_str(body, "zone_code")
    required_shift = v.req_enum(body, "required_shift", SHIFTS)
    intersection = domain.get_intersection(intersection_id)

    post = base_entity()
    post.update({
        "intersection_id": intersection["id"],
        "post_label": post_label,
        "zone_code": zone_code,
        "required_shift": required_shift,
        "status": "PROPOSED",
        "suspension_reason": None,
        "coverage_status": "UNSTAFFED",
        "open_gap_count": 0,
        "activated_at": None,
    })
    db.posts[post["id"]] = post
    touch(intersection)
    return object_response(post, 201)


@bp.get("/srts/guard-posts/<post_id>")
def read_post(post_id):
    require(*POST_READ_ROLES)
    post = domain.get_post(post_id)
    return object_response(post)


@bp.post("/srts/guard-posts/<post_id>/activate")
def activate_post(post_id):
    require("ProgramAdmin")
    post = domain.get_post(post_id)

    if post["status"] not in ("PROPOSED", "SUSPENDED"):
        fail("ERR_POST_NOT_ACTIVATABLE",
             "Only a PROPOSED or SUSPENDED post can be activated.")

    intersection = domain.get_intersection(post["intersection_id"])
    if intersection["warrant_status"] not in domain.WARRANT_PERMITTING:
        fail("ERR_POST_NOT_WARRANTED",
             "The intersection carries no standing warrant.")
    if (intersection["warrant_status"] == "CONDITIONAL"
            and post["required_shift"] != "AM"):
        fail("ERR_POST_SHIFT_NOT_PERMITTED",
             "A CONDITIONAL warrant permits morning coverage only.")

    post["status"] = "ACTIVE"
    post["activated_at"] = fmt_dt(now())
    post["suspension_reason"] = None
    touch(post)
    domain.propagate_from_post(post)
    return object_response(post)


@bp.post("/srts/guard-posts/<post_id>/assignments")
def create_assignment(post_id):
    require("CrossingSupervisor")
    body = v.body()
    guard_id = v.req_str(body, "guard_id")
    start_date = v.req_date(body, "start_date")
    end_date = v.req_date(body, "end_date")
    if end_date < start_date:
        bad_request("end_date must be on or after start_date.")
    expected_version = v.req_int(body, "expected_guard_post_version")

    post = domain.get_post(post_id)
    guard = domain.get_guard(guard_id)

    if post["status"] != "ACTIVE":
        fail("ERR_POST_NOT_ACTIVE", "A guard may only be assigned to an ACTIVE post.")
    if expected_version != post["version"]:
        fail("ERR_STALE_GUARD_POST_VERSION",
             "expected_guard_post_version does not match the stored version.")

    shift = post["required_shift"]

    if guard["certification_status"] != "CERTIFIED":
        fail("ERR_GUARD_NOT_CERTIFIED", "The named guard is not CERTIFIED.")
    expires_on = parse_date(guard["certification_expires_on"])
    if expires_on is None or expires_on < end_date:
        fail("ERR_GUARD_CERT_EXPIRED",
             "The guard's certification lapses before the assignment window ends.")
    if not guard["equipment_complete"]:
        fail("ERR_GUARD_EQUIPMENT_INCOMPLETE",
             "The named guard has not been issued all required equipment.")
    if guard["duty_status"] == "ON_LEAVE":
        fail("ERR_GUARD_ON_LEAVE", "The named guard is ON_LEAVE.")

    for other in domain.assignments_of_guard(guard):
        if other["status"] not in domain.LIVE_ASSIGNMENT_STATUSES:
            continue
        other_start = parse_date(other["start_date"])
        other_end = parse_date(other["end_date"])
        if not domain.ranges_overlap(start_date, end_date, other_start, other_end):
            continue
        if calc.shifts_conflict(shift, other["shift"]):
            fail("ERR_ASSIGNMENT_OVERLAP",
                 "The guard already holds a conflicting assignment over this window.")

    school = domain.school_of_post(post)
    session_start = parse_date(school["session_start_date"])
    session_end = parse_date(school["session_end_date"])
    if start_date < session_start or end_date > session_end:
        fail("ERR_ASSIGNMENT_OUTSIDE_SESSION",
             "The assignment window must lie inside the school's instructional session.")

    assignment = base_entity()
    assignment.update({
        "guard_post_id": post["id"],
        "guard_id": guard["id"],
        "shift": shift,
        "start_date": fmt_date(start_date),
        "end_date": fmt_date(end_date),
        "status": "SCHEDULED",
        "vacated_reason": None,
        "open_absence_count": 0,
        "coverage_state": "STAFFED",
    })
    db.assignments[assignment["id"]] = assignment

    _resolve_supersession(post, assignment, start_date, end_date, shift)

    if guard["duty_status"] == "UNASSIGNED":
        guard["duty_status"] = "ASSIGNED"
        touch(guard)

    touch(post)
    domain.propagate_from_post(post)
    return object_response(assignment, 201)


def _resolve_supersession(post, assignment, start_date, end_date, shift):
    """Supersession is resolved against the post, and start-date ordering alone
    decides termination versus truncation (PRD 3.5)."""
    released = []
    for incumbent in domain.assignments_of_post(post):
        if incumbent["id"] == assignment["id"]:
            continue
        if incumbent["status"] not in domain.LIVE_ASSIGNMENT_STATUSES:
            continue
        incumbent_start = parse_date(incumbent["start_date"])
        incumbent_end = parse_date(incumbent["end_date"])
        if not domain.ranges_overlap(start_date, end_date,
                                     incumbent_start, incumbent_end):
            continue
        if not calc.shifts_conflict(shift, incumbent["shift"]):
            continue
        if start_date <= incumbent_start:
            incumbent["status"] = "SUPERSEDED"
            touch(incumbent)
            released.append(incumbent["guard_id"])
        else:
            incumbent["end_date"] = fmt_date(add_days(start_date, -1))
            touch(incumbent)
    for guard_id in released:
        domain.release_guard(db.guards.get(guard_id))


@bp.get("/srts/post-assignments/<assignment_id>")
def read_assignment(assignment_id):
    require(*ASSIGNMENT_READ_ROLES)
    assignment = domain.get_assignment(assignment_id)
    return object_response(assignment)


@bp.get("/srts/post-assignments")
def list_assignments():
    require(*ASSIGNMENT_READ_ROLES)
    limit, offset = v.pagination()
    guard_post_id = v.query_filter("guard_post_id")
    guard_id = v.query_filter("guard_id")
    status = v.query_filter("status")
    records = list(db.assignments.values())
    if guard_post_id is not None:
        records = [a for a in records if a["guard_post_id"] == guard_post_id]
    if guard_id is not None:
        records = [a for a in records if a["guard_id"] == guard_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return list_response(records, limit, offset)
