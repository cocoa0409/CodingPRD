"""Flask app: routes for the course-registration API."""
import os

from flask import Flask, g, request

from core import (
    APPROVAL_TIMEOUT_SECONDS,
    DOWNSTREAM_ALL,
    DOWNSTREAM_FINANCE,
    DOWNSTREAM_OVER_LIMIT,
    DOWNSTREAM_PAID,
    LOCK,
    RAPID_SUBMIT_LIMIT,
    RAPID_SUBMIT_PENALTY,
    UNAUTHORIZED_DEPT_PENALTY,
    ApiError,
    bump,
    db,
    err,
    error_response,
    get_json_body,
    maybe,
    new_request_id,
    now_iso,
    ok,
    paginate,
    parse_auth,
    parse_pagination,
    require_field,
    require_roles,
    round2,
    stamp_create,
    stamp_create_immutable,
    sum_round2,
)
import domain
from domain import (
    _approve_enrollment,
    _waitlist_enrollment,
    base_quota_for,
    check_commute_conflict,
    check_exam_conflict,
    check_lab_equipment_conflict,
    check_time_conflict,
    cross_dept_access_ok,
    current_load_final,
    current_load_provisional,
    degree_plan_gap,
    downstream_unlock_count,
    effective_quota_provisional,
    emit_sync_event,
    instructor_weekly_minutes,
    offering_weekly_minutes,
    prereqs_satisfied,
    recent_submission_count,
    run_clock_auto_transitions,
    run_full_sweep,
    sweep_offering_waitlist,
    transferable_credits_for,
    waitlist_with_position,
)


app = Flask(__name__)


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------
@app.before_request
def _before():
    g.api_request_id = new_request_id()
    g._lock_token = LOCK.acquire()


@app.teardown_request
def _teardown(exc):
    try:
        if getattr(g, "_lock_token", False):
            LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_err(e):
    return error_response(e)


@app.errorhandler(404)
def _flask_404(e):
    return error_response(err("ERR_INVALID_STATE", "route not found"))


@app.errorhandler(405)
def _flask_405(e):
    return error_response(err("ERR_INSUFFICIENT_PERMISSIONS", "method not allowed"))


@app.errorhandler(Exception)
def _flask_exc(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_STATE", 500, str(e)))


@app.get("/healthz")
def healthz():
    return ok({"status": "ok"})


# ---------------------------------------------------------------------------
# Serializers (drop internal underscore-prefixed keys)
# ---------------------------------------------------------------------------
def serialize(entity: dict) -> dict:
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items):
    return [serialize(x) for x in items]


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(d, key, error_id):
    if key is None or key not in d:
        raise err(error_id)
    return d[key]


# ===========================================================================
# Departments
# ===========================================================================
@app.post("/departments")
def create_department():
    require_roles("Registrar")
    body = get_json_body()
    code = require_field(body, "code")
    name = require_field(body, "name")
    campus_id = require_field(body, "campus_id")
    if campus_id not in db.campuses:
        raise err("ERR_CAMPUS_NOT_FOUND")
    rec = stamp_create()
    rec.update({"code": code, "name": name, "campus_id": campus_id, "status": "ACTIVE"})
    db.departments[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/departments/<dep_id>")
def get_department(dep_id):
    require_roles("Registrar", "Student", "Professor")
    rec = get_or_404(db.departments, dep_id, "ERR_DEPARTMENT_NOT_FOUND")
    return ok(serialize(rec))


# ===========================================================================
# Campuses
# ===========================================================================
@app.post("/campuses")
def create_campus():
    require_roles("Registrar")
    body = get_json_body()
    code = require_field(body, "code")
    name = require_field(body, "name")
    commute = body.get("commute_minutes_to") or {}
    rec = stamp_create()
    rec.update({"code": code, "name": name, "commute_minutes_to": commute})
    db.campuses[rec["id"]] = rec
    return ok(serialize(rec), http=201)


# ===========================================================================
# Professors
# ===========================================================================
@app.post("/professors")
def create_professor():
    require_roles("Registrar")
    body = get_json_body()
    department_id = require_field(body, "department_id")
    full_name = require_field(body, "full_name")
    rank = require_field(body, "rank")
    is_chair = body.get("is_chair", False)
    max_min = require_field(body, "max_concurrent_teaching_minutes_per_week")
    if department_id not in db.departments:
        raise err("ERR_DEPARTMENT_NOT_FOUND")
    if rank not in ("ASSISTANT", "ASSOCIATE", "FULL"):
        raise err("ERR_REFERENTIAL_INTEGRITY", "invalid rank")
    if is_chair and rank not in ("ASSOCIATE", "FULL"):
        raise err("ERR_REFERENTIAL_INTEGRITY", "chair must be ASSOCIATE or FULL")
    rec = stamp_create()
    rec.update(
        {
            "department_id": department_id,
            "full_name": full_name,
            "rank": rank,
            "is_chair": bool(is_chair),
            "max_concurrent_teaching_minutes_per_week": int(max_min),
        }
    )
    db.professors[rec["id"]] = rec
    return ok(serialize(rec), http=201)


# ===========================================================================
# Lab equipment
# ===========================================================================
@app.post("/lab-equipment")
def create_lab_equipment():
    require_roles("Registrar")
    body = get_json_body()
    campus_id = require_field(body, "campus_id")
    name = require_field(body, "name")
    setup_buffer = body.get("setup_buffer_minutes", 0)
    if campus_id not in db.campuses:
        raise err("ERR_CAMPUS_NOT_FOUND")
    if int(setup_buffer) < 0:
        raise err("ERR_REFERENTIAL_INTEGRITY", "setup_buffer_minutes must be >= 0")
    rec = stamp_create()
    rec.update(
        {
            "campus_id": campus_id,
            "name": name,
            "setup_buffer_minutes": int(setup_buffer),
        }
    )
    db.lab_equipment[rec["id"]] = rec
    return ok(serialize(rec), http=201)


# ===========================================================================
# Terms
# ===========================================================================
@app.post("/terms")
def create_term():
    require_roles("Registrar")
    body = get_json_body()
    code = require_field(body, "code")
    rec = stamp_create()
    rec.update(
        {
            "code": code,
            "registration_open_at": int(require_field(body, "registration_open_at")),
            "registration_close_at": int(require_field(body, "registration_close_at")),
            "classes_start_at": int(require_field(body, "classes_start_at")),
            "exam_window_start_at": int(require_field(body, "exam_window_start_at")),
            "exam_window_end_at": int(require_field(body, "exam_window_end_at")),
            "status": "PLANNING",
        }
    )
    db.terms[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/terms/<term_id>")
def get_term(term_id):
    require_roles("Registrar", "Student", "Professor")
    rec = get_or_404(db.terms, term_id, "ERR_TERM_NOT_FOUND")
    return ok(serialize(rec))


@app.post("/terms/<term_id>/conclude")
def conclude_term(term_id):
    require_roles("Registrar")
    term = get_or_404(db.terms, term_id, "ERR_TERM_NOT_FOUND")
    if term["status"] != "IN_SESSION":
        raise err("ERR_INVALID_STATE", f"Term not in IN_SESSION (got {term['status']})")
    if db.clock < term["exam_window_end_at"]:
        raise err("ERR_TERM_NOT_READY_FOR_CONCLUDE")
    term["status"] = "CONCLUDED"
    bump(term)

    # Cascade enrollment finalization
    for ereq in list(db.enrollment_requests.values()):
        if ereq["term_id"] != term_id or ereq["academic_status"] != "APPROVED":
            continue
        student = db.students.get(ereq["student_id"])
        offering = db.course_offerings.get(ereq["offering_id"])
        course = db.courses.get(offering["course_id"]) if offering else None
        if ereq["financial_status"] == "PAID":
            ereq["academic_status"] = "SETTLED"
            if course:
                ereq["final_credit_charge"] = round2(course["credits"])
            bump(ereq)
        else:
            ereq["academic_status"] = "REJECTED"
            ereq["financial_status"] = "UNBILLED" if ereq["financial_status"] == "BILLED" else ereq["financial_status"]
            bump(ereq)
            emit_sync_event(
                "EnrollmentRequest", ereq["id"], "ENROLLMENT_CANCELED", DOWNSTREAM_ALL,
                payload={"reason": "TUITION_UNPAID"}, student_id=ereq["student_id"],
            )
    # Cascade offering IN_SESSION → CONCLUDED
    for offering in db.course_offerings.values():
        if offering["term_id"] == term_id and offering["status"] == "IN_SESSION":
            offering["status"] = "CONCLUDED"
            bump(offering)
    return ok(serialize(term))


# ===========================================================================
# Students
# ===========================================================================
@app.post("/students")
def create_student():
    require_roles("Registrar")
    body = get_json_body()
    full_name = require_field(body, "full_name")
    program_id = require_field(body, "program_id")
    program_dept = require_field(body, "program_department_id")
    home_campus = require_field(body, "home_campus_id")
    year = int(require_field(body, "year_in_program"))
    gpa = require_field(body, "gpa")
    completed = body.get("completed_course_ids") or []
    if program_dept not in db.departments:
        raise err("ERR_DEPARTMENT_NOT_FOUND")
    if home_campus not in db.campuses:
        raise err("ERR_CAMPUS_NOT_FOUND")
    if year < 1 or year > 6:
        raise err("ERR_REFERENTIAL_INTEGRITY", "year_in_program must be 1..6")
    rec = stamp_create()
    rec.update(
        {
            "full_name": full_name,
            "program_id": program_id,
            "program_department_id": program_dept,
            "home_campus_id": home_campus,
            "year_in_program": year,
            "gpa": float(gpa),
            "fraud_score": 0,
            "completed_course_ids": list(completed),
            "status": "ENROLLED",
        }
    )
    db.students[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/students")
def list_students():
    require_roles("Registrar")
    limit, offset = parse_pagination()
    items = sorted(db.students.values(), key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


@app.get("/students/<student_id>")
def get_student(student_id):
    user_id, role = require_roles("Registrar", "Student")
    rec = get_or_404(db.students, student_id, "ERR_STUDENT_NOT_FOUND")
    if role == "Student" and user_id != student_id:
        raise err("ERR_NOT_OWNER")
    return ok(serialize(rec))


@app.get("/students/<student_id>/degree-plan")
def get_degree_plan(student_id):
    user_id, role = require_roles("Registrar", "Student")
    student = get_or_404(db.students, student_id, "ERR_STUDENT_NOT_FOUND")
    if role == "Student" and user_id != student_id:
        raise err("ERR_NOT_OWNER")
    gap = degree_plan_gap(student)
    out = dict(gap)
    out["student_id"] = student_id
    out["transferable_credits"] = transferable_credits_for(student)
    return ok(out)


@app.get("/students/<student_id>/recommendations")
def get_recommendations(student_id):
    from core import REC_TOP_K, REC_W_GAP, REC_W_PREREQ_UNLOCK, REC_W_TIME_CONFLICT

    user_id, role = require_roles("Registrar", "Student")
    student = get_or_404(db.students, student_id, "ERR_STUDENT_NOT_FOUND")
    if role == "Student" and user_id != student_id:
        raise err("ERR_NOT_OWNER")
    gap = degree_plan_gap(student)
    gap_courses = set(gap["gap_courses"])

    # Pick "next open term" — earliest term currently in REGISTRATION_OPEN or REGISTRATION_CLOSED
    candidate_terms = [t for t in db.terms.values() if t["status"] in ("REGISTRATION_OPEN", "REGISTRATION_CLOSED", "PLANNING")]
    if not candidate_terms:
        return ok([], pagination={"limit": REC_TOP_K, "offset": 0, "total_count": 0, "has_more": False})
    target_term = sorted(candidate_terms, key=lambda t: t["registration_open_at"])[0]

    candidates = []
    for off in db.course_offerings.values():
        if off["term_id"] != target_term["id"]:
            continue
        if off["status"] != "OPEN":
            continue
        if off["course_id"] not in gap_courses:
            continue
        # time conflict count
        cnt_conflict = 0
        for ereq in db.enrollment_requests.values():
            if ereq["student_id"] != student["id"] or ereq["term_id"] != target_term["id"]:
                continue
            if ereq["academic_status"] != "APPROVED":
                continue
            existing = db.course_offerings.get(ereq["offering_id"])
            if not existing:
                continue
            for m_new in off.get("scheduled_meetings", []):
                for m_exist in existing.get("scheduled_meetings", []):
                    if domain.time_overlap_half_open(m_new, m_exist):
                        cnt_conflict += 1
        unlock = downstream_unlock_count(off["course_id"])
        score = REC_W_GAP * 1 + REC_W_PREREQ_UNLOCK * unlock - REC_W_TIME_CONFLICT * cnt_conflict
        candidates.append((score, off["id"], off))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    top = candidates[:REC_TOP_K]
    return ok([serialize(o) for _, _, o in top])


@app.get("/students/<student_id>/sync-events")
def get_student_sync_events(student_id):
    user_id, role = require_roles("Registrar", "Student")
    student = get_or_404(db.students, student_id, "ERR_STUDENT_NOT_FOUND")
    if role == "Student" and user_id != student_id:
        raise err("ERR_NOT_OWNER")
    limit, offset = parse_pagination()
    items = [e for e in db.sync_events if e.get("_student_id") == student_id]
    items.sort(key=lambda e: e["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


# ===========================================================================
# Courses
# ===========================================================================
@app.post("/courses")
def create_course():
    require_roles("Registrar")
    body = get_json_body()
    code = require_field(body, "code")
    title = require_field(body, "title")
    credits = float(require_field(body, "credits"))
    if credits <= 0:
        raise err("ERR_REFERENTIAL_INTEGRITY", "credits must be > 0")
    owning = require_field(body, "owning_department_id")
    if owning not in db.departments:
        raise err("ERR_DEPARTMENT_NOT_FOUND")
    rec = stamp_create()
    rec.update(
        {
            "code": code,
            "title": title,
            "credits": round2(credits),
            "owning_department_id": owning,
            "prerequisite_course_ids": list(body.get("prerequisite_course_ids") or []),
            "equivalent_course_ids": list(body.get("equivalent_course_ids") or []),
            "category": body.get("category"),
        }
    )
    db.courses[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/courses/<course_id>")
def get_course(course_id):
    require_roles("Registrar", "Student", "Professor")
    rec = get_or_404(db.courses, course_id, "ERR_COURSE_NOT_FOUND")
    return ok(serialize(rec))


# ===========================================================================
# Course Offerings
# ===========================================================================
@app.post("/course-offerings")
def create_offering():
    require_roles("Registrar")
    body = get_json_body()
    term_id = require_field(body, "term_id")
    course_id = require_field(body, "course_id")
    campus_id = require_field(body, "campus_id")
    instructor_id = require_field(body, "instructor_id")
    base_capacity = int(require_field(body, "base_capacity"))
    if base_capacity < 1:
        raise err("ERR_REFERENTIAL_INTEGRITY", "base_capacity must be >= 1")
    if term_id not in db.terms:
        raise err("ERR_TERM_NOT_FOUND")
    if course_id not in db.courses:
        raise err("ERR_COURSE_NOT_FOUND")
    if campus_id not in db.campuses:
        raise err("ERR_CAMPUS_NOT_FOUND")
    if instructor_id not in db.professors:
        raise err("ERR_PROFESSOR_NOT_FOUND")
    meetings = list(body.get("scheduled_meetings") or [])
    requires_lab = list(body.get("requires_lab_equipment_ids") or [])
    for lab_id in requires_lab:
        if lab_id not in db.lab_equipment:
            raise err("ERR_LAB_EQUIPMENT_NOT_FOUND")
    rec = stamp_create()
    rec.update(
        {
            "term_id": term_id,
            "course_id": course_id,
            "campus_id": campus_id,
            "instructor_id": instructor_id,
            "base_capacity": base_capacity,
            "capacity": base_capacity,
            "enrolled_count": 0,
            "scheduled_meetings": meetings,
            "requires_lab_equipment_ids": requires_lab,
            "status": "PLANNED",
        }
    )
    db.course_offerings[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/course-offerings")
def list_offerings():
    require_roles("Registrar", "Student", "Professor")
    limit, offset = parse_pagination()
    items = list(db.course_offerings.values())
    for k in ("term_id", "course_id", "campus_id", "instructor_id", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [o for o in items if o.get(k) == v]
    items.sort(key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


@app.get("/course-offerings/<offering_id>")
def get_offering(offering_id):
    require_roles("Registrar", "Student", "Professor")
    rec = get_or_404(db.course_offerings, offering_id, "ERR_OFFERING_NOT_FOUND")
    return ok(serialize(rec))


@app.post("/course-offerings/<offering_id>/open")
def open_offering(offering_id):
    require_roles("Registrar")
    offering = get_or_404(db.course_offerings, offering_id, "ERR_OFFERING_NOT_FOUND")
    if offering["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", f"Offering not in PLANNED (got {offering['status']})")
    term = db.terms.get(offering["term_id"])
    if not term or term["status"] != "REGISTRATION_OPEN":
        raise err("ERR_TERM_NOT_OPEN_FOR_REGISTRATION")
    instr = db.professors.get(offering["instructor_id"])
    if instr:
        existing = instructor_weekly_minutes(instr["id"], exclude_offering_id=offering["id"])
        new_min = offering_weekly_minutes(offering)
        if existing + new_min > instr["max_concurrent_teaching_minutes_per_week"]:
            raise err("ERR_INSTRUCTOR_TEACHING_LOAD_EXCEEDED")
    offering["status"] = "OPEN"
    bump(offering)
    return ok(serialize(offering))


@app.post("/course-offerings/<offering_id>/close")
def close_offering(offering_id):
    require_roles("Registrar")
    offering = get_or_404(db.course_offerings, offering_id, "ERR_OFFERING_NOT_FOUND")
    if offering["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", f"Offering not in OPEN (got {offering['status']})")
    offering["status"] = "CLOSED"
    bump(offering)
    # Cascade waitlist EXPIRED
    for w in db.waitlist_entries.values():
        if w["offering_id"] == offering_id and w["status"] == "ACTIVE":
            w["status"] = "EXPIRED"
    # Cascade SUBMITTED enrollment requests REJECTED
    for ereq in db.enrollment_requests.values():
        if ereq["offering_id"] == offering_id and ereq["academic_status"] == "SUBMITTED":
            ereq["academic_status"] = "REJECTED"
            bump(ereq)
    return ok(serialize(offering))


@app.patch("/course-offerings/<offering_id>/capacity")
def patch_offering_capacity(offering_id):
    require_roles("Registrar")
    offering = get_or_404(db.course_offerings, offering_id, "ERR_OFFERING_NOT_FOUND")
    body = get_json_body()
    if "new_capacity" not in body:
        raise err("ERR_REFERENTIAL_INTEGRITY", "new_capacity required")
    new_capacity = int(body["new_capacity"])
    if new_capacity < 1:
        raise err("ERR_REFERENTIAL_INTEGRITY", "new_capacity must be >= 1")
    if "version" in body and body["version"] is not None:
        if body["version"] != offering.get("version"):
            raise err("ERR_VERSION_CONFLICT")
    if offering["status"] not in ("PLANNED", "OPEN", "CLOSED"):
        raise err("ERR_INVALID_STATE", f"Cannot rescale in status {offering['status']}")

    cur_cap = offering.get("capacity", 0)
    enrolled = offering.get("enrolled_count", 0)
    if new_capacity > cur_cap:
        offering["capacity"] = new_capacity
        bump(offering)
        if offering["status"] == "OPEN":
            sweep_offering_waitlist(offering)
    elif new_capacity < cur_cap and new_capacity < enrolled:
        # Cancel (enrolled - new_capacity) lowest-priority APPROVED enrollments
        approved = [
            e
            for e in db.enrollment_requests.values()
            if e["offering_id"] == offering_id and e["academic_status"] == "APPROVED"
        ]
        # priority_score ASC (lowest first), created_at DESC (most recent first)
        approved.sort(key=lambda e: (e.get("priority_score") or 0, -_iso_to_epoch(e["created_at"])))
        to_cancel = enrolled - new_capacity
        canceled = approved[:to_cancel]
        for e in canceled:
            e["academic_status"] = "REJECTED"
            if e["financial_status"] == "BILLED":
                e["financial_status"] = "UNBILLED"
            bump(e)
            offering["enrolled_count"] -= 1
            emit_sync_event(
                "EnrollmentRequest", e["id"], "CAPACITY_REDUCED_CANCELED", DOWNSTREAM_ALL,
                payload={"offering_id": offering_id}, student_id=e["student_id"],
            )
        offering["capacity"] = new_capacity
        bump(offering)
    else:
        # new_capacity < cur_cap but >= enrolled — just shrink, no cascade
        offering["capacity"] = new_capacity
        bump(offering)

    return ok(serialize(offering))


def _iso_to_epoch(iso: str) -> float:
    from datetime import datetime
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()


@app.get("/course-offerings/<offering_id>/waitlist")
def list_offering_waitlist(offering_id):
    require_roles("Registrar", "Student", "Professor")
    if offering_id not in db.course_offerings:
        raise err("ERR_OFFERING_NOT_FOUND")
    limit, offset = parse_pagination()
    rows = waitlist_with_position(offering_id)
    # Order: ACTIVE rows by position; non-active appended (no position).
    rows.sort(key=lambda r: (0 if r.get("position") is not None else 1, r.get("position") or 0, r["created_at"]))
    sliced, page = paginate(rows, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


# ===========================================================================
# Enrollment requests
# ===========================================================================
@app.post("/enrollment-requests")
def submit_enrollment_request():
    user_id, role = require_roles("Student")
    body = get_json_body()
    student_id = require_field(body, "student_id")
    offering_id = require_field(body, "offering_id")
    if user_id != student_id:
        raise err("ERR_NOT_OWNER")
    student = get_or_404(db.students, student_id, "ERR_STUDENT_NOT_FOUND")
    offering = get_or_404(db.course_offerings, offering_id, "ERR_OFFERING_NOT_FOUND")
    course = db.courses.get(offering["course_id"])
    term = db.terms.get(offering["term_id"])
    if not course or not term:
        raise err("ERR_REFERENTIAL_INTEGRITY", "offering missing course/term")

    # Priority 4 state checks
    if term["status"] != "REGISTRATION_OPEN":
        raise err("ERR_TERM_NOT_OPEN_FOR_REGISTRATION")
    if offering["status"] != "OPEN":
        raise err("ERR_OFFERING_NOT_OPEN")

    # Priority 5 referential — basic
    # (No per-student term registration; trust offering→term consistency.)

    # Priority 6 cross-dept access
    if not cross_dept_access_ok(student, course):
        student["fraud_score"] = student.get("fraud_score", 0) + UNAUTHORIZED_DEPT_PENALTY
        bump(student)
        raise err("ERR_CROSS_DEPARTMENT_ACCESS_DENIED")

    # Priority 7 prereqs
    if not prereqs_satisfied(student, course):
        raise err("ERR_PREREQUISITE_NOT_MET")

    # Priority 8 time
    if check_time_conflict(student["id"], term["id"], offering):
        raise err("ERR_TIME_CONFLICT")

    # Priority 9 commute
    if check_commute_conflict(student["id"], term["id"], offering):
        raise err("ERR_COMMUTE_INFEASIBLE")

    # Priority 10 exam
    if check_exam_conflict(student["id"], term["id"], offering):
        raise err("ERR_EXAM_TIME_CONFLICT")

    # Priority 11 lab
    if check_lab_equipment_conflict(offering):
        raise err("ERR_LAB_EQUIPMENT_CONFLICT")

    # Priority 12 credit quota (variant_provisional)
    eq = effective_quota_provisional(student, term["id"])
    cur = current_load_provisional(student, term["id"])
    if cur + course["credits"] > eq:
        raise err("ERR_CREDIT_QUOTA_EXCEEDED")

    # Priority 13 anti-fraud rate limit
    if recent_submission_count(student["id"]) > RAPID_SUBMIT_LIMIT:
        student["fraud_score"] = student.get("fraud_score", 0) + RAPID_SUBMIT_PENALTY
        bump(student)
        raise err("ERR_RATE_LIMITED")

    # Create the EnrollmentRequest
    rec = stamp_create()
    rec.update(
        {
            "student_id": student_id,
            "offering_id": offering_id,
            "term_id": term["id"],
            "academic_status": "SUBMITTED",
            "financial_status": "UNBILLED",
            "priority_score": None,
            "provisional_credit_charge": None,
            "final_credit_charge": None,
            "_created_clock": db.clock,
        }
    )
    db.enrollment_requests[rec["id"]] = rec

    # Decision: approve vs waitlist
    if offering.get("enrolled_count", 0) < offering.get("capacity", 0):
        _approve_enrollment(rec, offering, course, student)
    else:
        _waitlist_enrollment(rec, offering, course, student)

    return ok(serialize(rec), http=201)


@app.get("/enrollment-requests/<request_id>")
def get_enrollment_request(request_id):
    user_id, role = require_roles("Registrar", "Student")
    rec = get_or_404(db.enrollment_requests, request_id, "ERR_REQUEST_NOT_FOUND")
    if role == "Student" and user_id != rec["student_id"]:
        raise err("ERR_NOT_OWNER")
    return ok(serialize(rec))


@app.get("/enrollment-requests")
def list_enrollment_requests():
    user_id, role = require_roles("Registrar", "Student")
    limit, offset = parse_pagination()
    items = list(db.enrollment_requests.values())
    sid = request.args.get("student_id")
    if role == "Student":
        if sid is None or sid != user_id:
            raise err("ERR_NOT_OWNER")
    if sid is not None:
        items = [e for e in items if e["student_id"] == sid]
    for k in ("term_id", "offering_id", "academic_status", "financial_status"):
        v = request.args.get(k)
        if v is not None:
            items = [e for e in items if e.get(k) == v]
    items.sort(key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


@app.post("/enrollment-requests/<request_id>/cancel")
def cancel_enrollment_request(request_id):
    user_id, role = require_roles("Student")
    rec = get_or_404(db.enrollment_requests, request_id, "ERR_REQUEST_NOT_FOUND")
    if user_id != rec["student_id"]:
        raise err("ERR_NOT_OWNER")
    offering = db.course_offerings.get(rec["offering_id"])
    course = db.courses.get(offering["course_id"]) if offering else None
    term = db.terms.get(rec["term_id"])
    if rec["academic_status"] not in ("APPROVED", "WAITLISTED"):
        raise err("ERR_INVALID_STATE", f"Cannot cancel from {rec['academic_status']}")
    if rec["academic_status"] == "APPROVED":
        if not term or term["status"] not in ("REGISTRATION_OPEN", "REGISTRATION_CLOSED") or db.clock >= term["classes_start_at"]:
            raise err("ERR_TERM_LOCKED_FOR_CANCEL")
        rec["academic_status"] = "CANCELED"
        if rec["financial_status"] == "BILLED":
            rec["financial_status"] = "UNBILLED"
        bump(rec)
        if offering:
            offering["enrolled_count"] = max(0, offering.get("enrolled_count", 0) - 1)
            bump(offering)
        emit_sync_event(
            "EnrollmentRequest", rec["id"], "ENROLLMENT_CANCELED", DOWNSTREAM_ALL,
            payload={"reason": "STUDENT_CANCEL"}, student_id=rec["student_id"],
        )
        # Trigger waitlist promotion sweep on this offering
        if offering and offering["status"] == "OPEN":
            sweep_offering_waitlist(offering)
    else:
        # WAITLISTED → CANCELED
        rec["academic_status"] = "CANCELED"
        bump(rec)
        for w in db.waitlist_entries.values():
            if w["enrollment_request_id"] == rec["id"] and w["status"] == "ACTIVE":
                w["status"] = "CANCELED"
    return ok(serialize(rec))


@app.post("/enrollment-requests/<request_id>/settle-tuition")
def settle_tuition(request_id):
    require_roles("Finance")
    rec = get_or_404(db.enrollment_requests, request_id, "ERR_REQUEST_NOT_FOUND")
    if rec["academic_status"] != "APPROVED":
        raise err("ERR_INVALID_STATE_FOR_SETTLE")
    if rec["financial_status"] != "BILLED":
        raise err("ERR_INVALID_STATE_FOR_SETTLE")
    rec["financial_status"] = "PAID"
    bump(rec)
    emit_sync_event(
        "EnrollmentRequest", rec["id"], "TUITION_PAID", DOWNSTREAM_PAID,
        payload={"student_id": rec["student_id"]}, student_id=rec["student_id"],
    )
    return ok(serialize(rec))


# ===========================================================================
# Over-limit applications
# ===========================================================================
@app.post("/over-limit-applications")
def create_over_limit_app():
    user_id, role = require_roles("Student")
    body = get_json_body()
    student_id = require_field(body, "student_id")
    if user_id != student_id:
        raise err("ERR_NOT_OWNER")
    term_id = require_field(body, "term_id")
    requested = require_field(body, "requested_extension_credits")
    if float(requested) <= 0:
        raise err("ERR_REFERENTIAL_INTEGRITY", "requested_extension_credits must be > 0")
    justification = require_field(body, "justification")
    primary_id = require_field(body, "primary_signer_id")
    secondary_id = require_field(body, "secondary_signer_id")
    student = get_or_404(db.students, student_id, "ERR_STUDENT_NOT_FOUND")
    term = get_or_404(db.terms, term_id, "ERR_TERM_NOT_FOUND")
    primary = get_or_404(db.professors, primary_id, "ERR_PROFESSOR_NOT_FOUND")
    secondary = get_or_404(db.professors, secondary_id, "ERR_PROFESSOR_NOT_FOUND")
    home_dept = student["program_department_id"]
    # Priority 5 referential checks
    if primary["department_id"] != home_dept or secondary["department_id"] != home_dept:
        raise err("ERR_SIGNER_NOT_IN_HOME_DEPARTMENT")
    if primary.get("is_chair"):
        raise err("ERR_PRIMARY_SIGNER_IS_CHAIR")
    if not secondary.get("is_chair"):
        raise err("ERR_SECONDARY_SIGNER_NOT_CHAIR")

    # Priority 13 anti-fraud rate limit also applies per scaffold
    if recent_submission_count(student["id"]) > RAPID_SUBMIT_LIMIT:
        student["fraud_score"] = student.get("fraud_score", 0) + RAPID_SUBMIT_PENALTY
        bump(student)
        raise err("ERR_RATE_LIMITED")

    rec = stamp_create()
    rec.update(
        {
            "student_id": student_id,
            "term_id": term_id,
            "requested_extension_credits": round2(float(requested)),
            "justification": justification,
            "primary_signer_id": primary_id,
            "secondary_signer_id": secondary_id,
            "granted_credits": 0,
            "timeout_deadline_at": None,
            "status": "DRAFT",
        }
    )
    db.over_limit_applications[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/over-limit-applications/<app_id>")
def get_over_limit_app(app_id):
    require_roles("Registrar", "Student", "Professor")
    rec = get_or_404(db.over_limit_applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    return ok(serialize(rec))


@app.post("/over-limit-applications/<app_id>/submit")
def submit_over_limit_app(app_id):
    user_id, role = require_roles("Student")
    rec = get_or_404(db.over_limit_applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    if user_id != rec["student_id"]:
        raise err("ERR_NOT_OWNER")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", f"Cannot submit from {rec['status']}")
    term = db.terms.get(rec["term_id"])
    if not term or term["status"] != "REGISTRATION_OPEN":
        raise err("ERR_TERM_NOT_OPEN_FOR_REGISTRATION")
    rec["status"] = "AWAITING_PRIMARY"
    rec["timeout_deadline_at"] = db.clock + APPROVAL_TIMEOUT_SECONDS
    bump(rec)
    return ok(serialize(rec))


@app.post("/over-limit-applications/<app_id>/sign")
def sign_over_limit_app(app_id):
    user_id, role = require_roles("Professor")
    rec = get_or_404(db.over_limit_applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if body["version"] != rec.get("version"):
            raise err("ERR_VERSION_CONFLICT")
    if rec["status"] not in ("AWAITING_PRIMARY", "AWAITING_SECONDARY"):
        raise err("ERR_INVALID_STATE", f"Cannot sign from {rec['status']}")
    if rec["status"] == "AWAITING_PRIMARY":
        if user_id != rec["primary_signer_id"]:
            raise err("ERR_NOT_DESIGNATED_SIGNER")
        rec["status"] = "AWAITING_SECONDARY"
        rec["timeout_deadline_at"] = db.clock + APPROVAL_TIMEOUT_SECONDS
        bump(rec)
    else:
        if user_id != rec["secondary_signer_id"]:
            raise err("ERR_NOT_DESIGNATED_SIGNER")
        rec["status"] = "APPROVED"
        rec["granted_credits"] = rec["requested_extension_credits"]
        bump(rec)
        emit_sync_event(
            "OverLimitApplication", rec["id"], "OVER_LIMIT_GRANTED", DOWNSTREAM_OVER_LIMIT,
            payload={"student_id": rec["student_id"], "term_id": rec["term_id"], "granted_credits": rec["granted_credits"]},
            student_id=rec["student_id"],
        )
    return ok(serialize(rec))


@app.post("/over-limit-applications/<app_id>/reject")
def reject_over_limit_app(app_id):
    user_id, role = require_roles("Professor")
    rec = get_or_404(db.over_limit_applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if body["version"] != rec.get("version"):
            raise err("ERR_VERSION_CONFLICT")
    if rec["status"] not in ("AWAITING_PRIMARY", "AWAITING_SECONDARY"):
        raise err("ERR_INVALID_STATE", f"Cannot reject from {rec['status']}")
    if rec["status"] == "AWAITING_PRIMARY":
        if user_id != rec["primary_signer_id"]:
            raise err("ERR_NOT_DESIGNATED_SIGNER")
    else:
        if user_id != rec["secondary_signer_id"]:
            raise err("ERR_NOT_DESIGNATED_SIGNER")
    rec["status"] = "REJECTED"
    bump(rec)
    return ok(serialize(rec))


@app.post("/over-limit-applications/<app_id>/revise")
def revise_over_limit_app(app_id):
    user_id, role = require_roles("Student")
    rec = get_or_404(db.over_limit_applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    if user_id != rec["student_id"]:
        raise err("ERR_NOT_OWNER")
    if rec["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", f"Cannot revise from {rec['status']}")
    term = db.terms.get(rec["term_id"])
    if not term or term["status"] != "REGISTRATION_OPEN":
        raise err("ERR_TERM_NOT_OPEN_FOR_REGISTRATION")
    rec["status"] = "DRAFT"
    rec["granted_credits"] = 0
    rec["timeout_deadline_at"] = None
    bump(rec)
    return ok(serialize(rec))


# ===========================================================================
# Department access grants
# ===========================================================================
@app.post("/department-access-grants")
def create_grant():
    require_roles("Registrar")
    body = get_json_body()
    src = require_field(body, "source_department_id")
    tgt = require_field(body, "target_department_id")
    cats = body.get("course_categories_allowed")
    if cats is None:
        raise err("ERR_REFERENTIAL_INTEGRITY", "course_categories_allowed required")
    bidir = body.get("bidirectional", False)
    if src not in db.departments or tgt not in db.departments:
        raise err("ERR_DEPARTMENT_NOT_FOUND")
    rec = stamp_create()
    rec.update(
        {
            "source_department_id": src,
            "target_department_id": tgt,
            "course_categories_allowed": list(cats),
            "bidirectional": bool(bidir),
            "status": "ACTIVE",
        }
    )
    db.department_access_grants[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/department-access-grants")
def list_grants():
    require_roles("Registrar", "Student")
    limit, offset = parse_pagination()
    items = list(db.department_access_grants.values())
    for k in ("source_department_id", "target_department_id", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [g for g in items if g.get(k) == v]
    items.sort(key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


@app.post("/department-access-grants/<grant_id>/revoke")
def revoke_grant(grant_id):
    require_roles("Registrar")
    rec = get_or_404(db.department_access_grants, grant_id, "ERR_GRANT_NOT_FOUND")
    if rec["status"] == "REVOKED":
        raise err("ERR_INVALID_STATE", "already revoked")
    rec["status"] = "REVOKED"
    bump(rec)
    return ok(serialize(rec))


# ===========================================================================
# Credit equivalence policies
# ===========================================================================
@app.post("/credit-equivalence-policies")
def create_policy():
    require_roles("Registrar")
    body = get_json_body()
    src_prog = require_field(body, "source_program_id")
    tgt_prog = require_field(body, "target_program_id")
    src_course = require_field(body, "source_course_id")
    tgt_course = require_field(body, "target_course_id")
    factor = float(require_field(body, "transfer_factor"))
    if not (0 < factor <= 1.0):
        raise err("ERR_REFERENTIAL_INTEGRITY", "transfer_factor must be in (0,1]")
    if src_course not in db.courses or tgt_course not in db.courses:
        raise err("ERR_COURSE_NOT_FOUND")
    rec = stamp_create_immutable()
    rec.update(
        {
            "source_program_id": src_prog,
            "target_program_id": tgt_prog,
            "source_course_id": src_course,
            "target_course_id": tgt_course,
            "transfer_factor": factor,
        }
    )
    db.credit_equivalence_policies[rec["id"]] = rec
    return ok(serialize(rec), http=201)


@app.get("/credit-equivalence-policies")
def list_policies():
    require_roles("Registrar", "Student")
    limit, offset = parse_pagination()
    items = list(db.credit_equivalence_policies.values())
    for k in ("source_program_id", "target_program_id"):
        v = request.args.get(k)
        if v is not None:
            items = [p for p in items if p.get(k) == v]
    items.sort(key=lambda x: x["created_at"])
    sliced, page = paginate(items, limit, offset)
    return ok(serialize_list(sliced), pagination=page)


# ===========================================================================
# Test-driving endpoints
# ===========================================================================
@app.post("/_clock/advance")
def clock_advance():
    require_roles("Registrar")
    body = get_json_body()
    target = int(require_field(body, "target_unix_seconds"))
    if target < db.clock:
        raise err("ERR_REFERENTIAL_INTEGRITY", "clock cannot move backward")
    db.clock = target
    run_clock_auto_transitions()
    return ok({"clock": db.clock})


@app.post("/_sweep/run")
def sweep_run():
    require_roles("Registrar")
    run_full_sweep()
    return ok({"clock": db.clock})


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
