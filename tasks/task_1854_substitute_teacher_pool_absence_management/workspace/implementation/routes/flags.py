"""PerformanceFlag endpoints: raise (reliability event appended at once),
list per substitute/school, review (resolve or escalate into DNR)."""

from flask import Blueprint

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_SUBSTITUTE_NOT_FOUND, ERR_SCHOOL_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND, ERR_PERFORMANCE_FLAG_NOT_FOUND,
    ERR_PERFORMANCE_FLAG_INVALID_STATE,
)
from middleware import auth_context, require_role, require_coordinator_school, ALL_ROLES
from response import ok, paginated
from validate import body, req_str, req_enum, opt_str

bp = Blueprint("flags", __name__)

FLAG_TYPES = ("NO_SHOW", "CONDUCT", "QUALITY", "TARDINESS")
SEVERITIES = ("MINOR", "MAJOR")


@bp.route("/performance-flags", methods=["POST"])
def create_flag():
    user_id, role = auth_context()
    data = body()
    substitute_id = req_str(data, "substitute_id")
    school_id = req_str(data, "school_id")
    flag_type = req_enum(data, "flag_type", FLAG_TYPES)
    severity = req_enum(data, "severity", SEVERITIES)
    assignment_id = opt_str(data, "assignment_id")
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, school_id)
    sub = STORE.substitutes.get(substitute_id)
    if sub is None:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    school = STORE.schools.get(school_id)
    if school is None:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school id does not exist")
    if assignment_id is not None and assignment_id not in STORE.assignments:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "assignment id does not exist")
    f = new_entity(STORE.flags, {
        "substitute_id": substitute_id,
        "school_id": school_id,
        "assignment_id": assignment_id,
        "flag_type": flag_type,
        "severity": severity,
        "status": "OPEN",
        "auto_created": False,
    })
    # Raising a flag immediately appends the matching reliability event and
    # runs suspension evaluation: flags move scores before any human review.
    district = domain.school_district(school)
    event = "FLAG_MAJOR" if severity == "MAJOR" else "FLAG_MINOR"
    domain.refresh_substitute_scores(sub)
    domain.append_event(sub, event, assignment_id=assignment_id, district=district)
    return ok(public(f), status=201)


@bp.route("/substitutes/<sid>/performance-flags", methods=["GET"])
def list_substitute_flags(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if sid not in STORE.substitutes:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    items = sorted((f for f in STORE.flags.values() if f["substitute_id"] == sid),
                   key=lambda f: (f["created_at"], f["_seq"]))
    page, meta = paginated(items)
    return ok([public(f) for f in page], pagination=meta)


@bp.route("/schools/<sid>/performance-flags", methods=["GET"])
def list_school_flags(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if sid not in STORE.schools:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school id does not exist")
    items = sorted((f for f in STORE.flags.values() if f["school_id"] == sid),
                   key=lambda f: (f["created_at"], f["_seq"]))
    page, meta = paginated(items)
    return ok([public(f) for f in page], pagination=meta)


@bp.route("/performance-flags/<fid>/review", methods=["POST"])
def review_flag(fid):
    _, role = auth_context()
    data = body()
    decision = req_enum(data, "decision", ("RESOLVE", "ESCALATE"))
    require_role(role, ["DistrictAdmin"])
    f = STORE.flags.get(fid)
    if f is None:
        raise_err(ERR_PERFORMANCE_FLAG_NOT_FOUND, "performance flag id does not exist")
    if f["status"] != "OPEN":
        raise_err(ERR_PERFORMANCE_FLAG_INVALID_STATE, "review requires status OPEN")
    if decision == "RESOLVE":
        f["status"] = "RESOLVED"
        touch(f)
        return ok(public(f))
    f["status"] = "ESCALATED"
    touch(f)
    # Escalation converts the flag into exclusion: an ACTIVE DO_NOT_RETURN
    # mark pointing back at the flag (unless one exists), then the cascade.
    if domain.active_mark(f["school_id"], f["substitute_id"], "DO_NOT_RETURN") is None:
        new_entity(STORE.marks, {
            "school_id": f["school_id"],
            "substitute_id": f["substitute_id"],
            "mark_type": "DO_NOT_RETURN",
            "priority_rank": None,
            "reason": None,
            "status": "ACTIVE",
            "source_flag_id": f["id"],
        })
    domain.dnr_cascade(f["school_id"], f["substitute_id"])
    return ok(public(f))
