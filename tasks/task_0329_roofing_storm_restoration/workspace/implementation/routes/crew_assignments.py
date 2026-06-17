"""CrewAssignment resource: book, read, list, check-in, complete, cancel."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
from timeutil import parse_iso8601
import validators as V

bp = Blueprint("crew_assignments", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}


@bp.route("/crew-assignments", methods=["POST"])
def create_assignment():
    require_role({"ProductionManager"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    crew_id = V.require_field(body, "crew_id")
    window_start = V.require_field(body, "window_start")
    window_end = V.require_field(body, "window_end")
    if not isinstance(job_id, str):
        V.missing_field("job_id")
    if not isinstance(crew_id, str):
        V.missing_field("crew_id")

    # FK (priority 4)
    V.resolve_fk(db.jobs, job_id)
    V.resolve_fk(db.crews, crew_id)

    # interval validity (priority 6)
    start_dt = parse_iso8601(window_start)
    end_dt = parse_iso8601(window_end)
    if start_dt is None or end_dt is None:
        V.invalid_request("window_start/window_end must be ISO 8601")
    if not (end_dt > start_dt):
        V.invalid_request("window_end must be after window_start")

    with db.lock:
        # temporal (priority 9): half-open overlap for the same crew
        _check_overlap(crew_id, start_dt, end_dt)
        ent = common_create_fields(versioned=True)
        ent.update({
            "job_id": job_id,
            "crew_id": crew_id,
            "window_start": window_start,
            "window_end": window_end,
            "status": "BOOKED",
        })
        db.crew_assignments[ent["id"]] = ent
    return success(ent, status=201)


def _check_overlap(crew_id, new_start, new_end):
    """Half-open conflict: new.start < e.end AND e.start < new.end, against
    BOOKED/CHECKED_IN assignments for the same crew."""
    for ca in db.crew_assignments.values():
        if ca["crew_id"] != crew_id or ca["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        e_start = parse_iso8601(ca["window_start"])
        e_end = parse_iso8601(ca["window_end"])
        if new_start < e_end and e_start < new_end:
            raise ApiError(errors.ERR_CREW_DOUBLE_BOOKED, 409,
                           "Crew window double-booked")


@bp.route("/crew-assignments/<entity_id>", methods=["GET"])
def get_assignment(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.crew_assignments, entity_id)
    return success(ent, status=200)


@bp.route("/crew-assignments", methods=["GET"])
def list_assignments():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.crew_assignments.values())
    for key in ("job_id", "crew_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/crew-assignments/<entity_id>/check-in", methods=["POST"])
def check_in(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        ca = V.find_or_404(db.crew_assignments, entity_id)
        if ca["status"] != "BOOKED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Assignment not BOOKED")
        # cross-entity (priority 8): job IN_PRODUCTION, then crew active
        job = db.jobs.get(ca["job_id"])
        if job is None or job["status"] != "IN_PRODUCTION":
            raise ApiError(errors.ERR_JOB_NOT_IN_PRODUCTION, 409,
                           "Job not IN_PRODUCTION")
        crew = db.crews.get(ca["crew_id"])
        if crew is None or not crew.get("active", False):
            raise ApiError(errors.ERR_CREW_INACTIVE, 409,
                           "Crew is inactive")
        ca["status"] = "CHECKED_IN"
        touch(ca)
        return success(ca, status=200)


@bp.route("/crew-assignments/<entity_id>/complete", methods=["POST"])
def complete_assignment(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        ca = V.find_or_404(db.crew_assignments, entity_id)
        if ca["status"] != "CHECKED_IN":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Assignment not CHECKED_IN")
        ca["status"] = "COMPLETED"
        touch(ca)
        return success(ca, status=200)


@bp.route("/crew-assignments/<entity_id>/cancel", methods=["POST"])
def cancel_assignment(entity_id):
    require_role({"ProductionManager"})
    with db.lock:
        ca = V.find_or_404(db.crew_assignments, entity_id)
        if ca["status"] != "BOOKED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Assignment not BOOKED")
        ca["status"] = "CANCELLED"
        touch(ca)
        return success(ca, status=200)
