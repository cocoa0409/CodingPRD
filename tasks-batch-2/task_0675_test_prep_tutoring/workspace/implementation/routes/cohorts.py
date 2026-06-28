"""Cohort endpoints + lifecycle state machine (PRD §3.1, §3.2)."""
from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_auth, get_json_body, parse_pagination, parse_iso8601
from services import serialize, validators, core
from services.listing import sort_and_page

bp = Blueprint("cohorts", __name__)


def _windows_overlap_half_open(a_start, a_end, b_start, b_end):
    # Half-open overlap (PRD §3.2): (A.starts < B.ends) AND (B.starts < A.ends).
    return a_start < b_end and b_start < a_end


def _windows_overlap_closed(a_start, a_end, b_start, b_end):
    # Closed-interval, buffer-inclusive (PRD §3.4): touching boundaries conflict.
    return a_start <= b_end and b_start <= a_end


@bp.post("/cohorts")
def create_cohort():
    require_auth({"Registrar"})
    body = get_json_body()

    course_id = validators.require_str(body, "course_id")
    seat_capacity = validators.require_int(body, "seat_capacity", minimum=1)
    starts_at_raw = validators.require_str(body, "starts_at")
    ends_at_raw = validators.require_str(body, "ends_at")
    total_sessions = validators.require_int(body, "total_sessions", minimum=1)

    # Existence of body FK (priority 3) before body well-formedness of the
    # datetime ordering — but field type validity is part of priority 4. We
    # resolve the FK first per §2.5 (body FKs after required-field presence is
    # impractical to separate; existence is checked here explicitly).
    course = db.courses.get(course_id)
    if course is None:
        raise err("ERR_NOT_FOUND", "Course not found.")

    starts_at = parse_iso8601(starts_at_raw, "starts_at")
    ends_at = parse_iso8601(ends_at_raw, "ends_at")
    if not (ends_at > starts_at):
        raise err("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at.")

    rec = {
        "id": db.new_id(),
        "course_id": course_id,
        "instructor_id": None,
        "seat_capacity": seat_capacity,
        "seats_committed": 0,
        "starts_at": db._iso(starts_at),
        "ends_at": db._iso(ends_at),
        "total_sessions": total_sessions,
        "status": "DRAFT",
    }
    db.stamp_create(rec)
    db.cohorts[rec["id"]] = rec
    return response.success(serialize.cohort(rec), 201)


@bp.get("/cohorts/<cid>")
def get_cohort(cid):
    cohort = db.cohorts.get(cid)
    if cohort is None:
        raise err("ERR_NOT_FOUND", "Cohort not found.")
    return response.success(serialize.cohort(cohort), 200)


@bp.post("/cohorts/<cid>/schedule")
def schedule_cohort(cid):
    require_auth({"Registrar"})
    cohort = db.cohorts.get(cid)
    if cohort is None:
        raise err("ERR_NOT_FOUND", "Cohort not found.")
    body = get_json_body()
    instructor_id = validators.require_str(body, "instructor_id")
    instructor = db.instructors.get(instructor_id)
    if instructor is None:
        raise err("ERR_NOT_FOUND", "Instructor not found.")

    # State legality first (priority 6).
    if cohort["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Cohort is not DRAFT.")

    course = db.courses[cohort["course_id"]]
    # Business rules in PRD §3.2 order: course published, certification, load,
    # time conflict. (Validation priorities 7-9 + course-not-published.)
    if course["status"] != "PUBLISHED":
        raise err("ERR_COURSE_NOT_PUBLISHED", "Parent course is not PUBLISHED.")
    if course["exam_type"] not in instructor["certified_exam_types"]:
        raise err(
            "ERR_INSTRUCTOR_NOT_CERTIFIED",
            "Instructor is not certified for the course exam type.",
        )
    if instructor["active_cohort_count"] >= instructor["max_concurrent_cohorts"]:
        raise err("ERR_INSTRUCTOR_OVERLOADED", "Instructor is at max concurrent cohorts.")

    a_start = parse_iso8601(cohort["starts_at"])
    a_end = parse_iso8601(cohort["ends_at"])
    for other in db.cohorts.values():
        if other["id"] == cohort["id"]:
            continue
        if other["instructor_id"] != instructor_id:
            continue
        if other["status"] not in ("SCHEDULED", "IN_SESSION"):
            continue
        b_start = parse_iso8601(other["starts_at"])
        b_end = parse_iso8601(other["ends_at"])
        if _windows_overlap_half_open(a_start, a_end, b_start, b_end):
            raise err(
                "ERR_INSTRUCTOR_TIME_CONFLICT",
                "Instructor has an overlapping cohort window.",
            )

    # Side effects.
    cohort["instructor_id"] = instructor_id
    cohort["status"] = "SCHEDULED"
    db.touch(cohort)
    instructor["active_cohort_count"] += 1
    db.touch(instructor)
    return response.success(serialize.cohort(cohort), 200)


@bp.post("/cohorts/<cid>/start")
def start_cohort(cid):
    require_auth({"Registrar"})
    cohort = db.cohorts.get(cid)
    if cohort is None:
        raise err("ERR_NOT_FOUND", "Cohort not found.")
    if cohort["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Cohort is not SCHEDULED.")
    starts_at = parse_iso8601(cohort["starts_at"])
    if db.now_clock() < starts_at:
        raise err("ERR_COHORT_WINDOW_NOT_OPEN", "Clock has not reached starts_at.")
    cohort["status"] = "IN_SESSION"
    db.touch(cohort)
    return response.success(serialize.cohort(cohort), 200)


@bp.post("/cohorts/<cid>/conclude")
def conclude_cohort(cid):
    require_auth({"Registrar"})
    cohort = db.cohorts.get(cid)
    if cohort is None:
        raise err("ERR_NOT_FOUND", "Cohort not found.")
    if cohort["status"] != "IN_SESSION":
        raise err("ERR_INVALID_STATE", "Cohort is not IN_SESSION.")
    ends_at = parse_iso8601(cohort["ends_at"])
    if db.now_clock() < ends_at:
        raise err("ERR_COHORT_WINDOW_NOT_OPEN", "Clock has not reached ends_at.")

    cohort["status"] = "CONCLUDED"
    db.touch(cohort)

    # Complete every ACTIVE enrollment; each completion evaluates the guarantee.
    active_enrollments = [
        e
        for e in db.enrollments.values()
        if e["cohort_id"] == cohort["id"] and e["status"] == "ACTIVE"
    ]
    for e in sorted(active_enrollments, key=lambda r: r["_seq"]):
        e["status"] = "COMPLETED"
        db.touch(e)
        core.evaluate_guarantee(e)

    # Decrement the assigned instructor's active_cohort_count.
    if cohort["instructor_id"] is not None:
        inst = db.instructors.get(cohort["instructor_id"])
        if inst is not None:
            core.recompute_active_cohort_count(inst)
    return response.success(serialize.cohort(cohort), 200)


@bp.post("/cohorts/<cid>/cancel")
def cancel_cohort(cid):
    require_auth({"Registrar"})
    cohort = db.cohorts.get(cid)
    if cohort is None:
        raise err("ERR_NOT_FOUND", "Cohort not found.")
    if cohort["status"] not in ("DRAFT", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Cohort is not DRAFT or SCHEDULED.")

    cohort["status"] = "CANCELLED"
    db.touch(cohort)

    # Cascade-cancel enrollments in {ACTIVE, WAITLISTED, PENDING_PAYMENT}.
    to_cancel = [
        e
        for e in db.enrollments.values()
        if e["cohort_id"] == cohort["id"]
        and e["status"] in ("ACTIVE", "WAITLISTED", "PENDING_PAYMENT")
    ]
    for e in sorted(to_cancel, key=lambda r: r["_seq"]):
        # Re-check status: a prior cancellation's waitlist promotion may have
        # moved a WAITLISTED enrollment to PENDING_PAYMENT (still cancellable).
        if e["status"] in ("ACTIVE", "WAITLISTED", "PENDING_PAYMENT"):
            core.cancel_enrollment(e)

    if cohort["instructor_id"] is not None:
        inst = db.instructors.get(cohort["instructor_id"])
        if inst is not None:
            core.recompute_active_cohort_count(inst)
    return response.success(serialize.cohort(cohort), 200)


@bp.get("/cohorts/<cid>/enrollments")
def list_cohort_enrollments(cid):
    require_auth({"Registrar", "Instructor"})
    cohort = db.cohorts.get(cid)
    if cohort is None:
        raise err("ERR_NOT_FOUND", "Cohort not found.")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [e for e in db.enrollments.values() if e["cohort_id"] == cid]
    if status is not None:
        records = [e for e in records if e["status"] == status]
    page, total = sort_and_page(records, limit, offset)
    return response.success_list(
        [serialize.enrollment(e) for e in page], limit, offset, total
    )
