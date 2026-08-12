"""Logical clock, advisors (incl. deactivate/reassign/equity), teachers, pathways."""

from flask import Blueprint, g

from store import stores, mint, bump, set_clock, fmt_ts
from util import (
    ok_object, paginate, fail, get_body, validate_schema, require_role,
    parse_datetime, sort_records,
    ERR_VALIDATION, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_STALE_VERSION,
    ERR_INVALID_STATE, ERR_DUPLICATE_CODE, ERR_NO_ADVISOR_AVAILABLE,
)
from computed import (
    ser_advisor, ser_teacher, ser_pathway, ser_student, ser_audit,
    active_caseload_count, caseload_load_weighted, equity_gap_index,
    target_caseload, district_totals, students_of_advisor,
)

bp = Blueprint("admin", __name__)

ADVISOR_STATUSES = ("ACTIVE", "INACTIVE")
TEACHER_STATUSES = ("ACTIVE", "INACTIVE")
PATHWAY_STATUSES = ("ACTIVE", "RETIRED")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def clock_set():
    body = get_body()
    validate_schema(body, {"to_iso8601": {"kind": "datetime", "required": True}})
    require_role(g.user_role, "DistrictAdmin")
    set_clock(parse_datetime(body["to_iso8601"]))
    return ok_object({"current_utc": fmt_ts(parse_datetime(body["to_iso8601"]))}, 200)


# ---------------------------------------------------------------------------
# Advisors
# ---------------------------------------------------------------------------

@bp.post("/ccr/advisors")
def advisor_create():
    body = get_body()
    validate_schema(body, {
        "full_name": {"kind": "str", "required": True},
        "email": {"kind": "str", "required": True},
        "max_caseload": {"kind": "int", "required": True, "min": 1},
    })
    require_role(g.user_role, "DistrictAdmin")
    if any(a["email"] == body["email"] for a in stores["advisors"].values()):
        fail(ERR_DUPLICATE_CODE, 409, "email already in use")
    rec = mint("advisors")
    rec.update({
        "full_name": body["full_name"],
        "email": body["email"],
        "max_caseload": body["max_caseload"],
        "status": "ACTIVE",
    })
    stores["advisors"][rec["id"]] = rec
    return ok_object(ser_advisor(rec), 201)


def _get_advisor(aid):
    a = stores["advisors"].get(aid)
    if a is None:
        fail(ERR_NOT_FOUND, 404, "Advisor not found")
    return a


@bp.get("/ccr/advisors/<aid>")
def advisor_get(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    return ok_object(ser_advisor(_get_advisor(aid)), 200)


@bp.get("/ccr/advisors/<aid>/students")
def advisor_students(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    _get_advisor(aid)
    items = [s for s in stores["students"].values() if s["assigned_advisor_id"] == aid]
    status = None
    from flask import request
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate(items, ser_student)


@bp.get("/ccr/advisors/<aid>/senior-audits")
def advisor_audits(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    _get_advisor(aid)
    items = [a for a in stores["audits"].values() if a["auditor_advisor_id"] == aid]
    return paginate(items, ser_audit)


def _selector_pool(exclude_id=None, counts_override=None):
    """ACTIVE advisors with spare capacity; rank count ASC then created_at ASC."""
    pool = []
    for a in stores["advisors"].values():
        if a["status"] != "ACTIVE":
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        cnt = counts_override.get(a["id"]) if counts_override is not None else active_caseload_count(a["id"])
        if cnt < a["max_caseload"]:
            pool.append((a, cnt))
    pool.sort(key=lambda t: (t[1], t[0]["created_at"], t[0]["_seq"]))
    return pool


@bp.post("/ccr/advisors/<aid>/deactivate")
def advisor_deactivate(aid):
    body = get_body()
    validate_schema(body, {"reactivate": {"kind": "bool", "required": False}})
    require_role(g.user_role, "DistrictAdmin")
    advisor = _get_advisor(aid)
    reactivate = body.get("reactivate", False)
    if reactivate:
        if advisor["status"] != "INACTIVE":
            fail(ERR_INVALID_STATE, 409, "Advisor is not INACTIVE")
        advisor["status"] = "ACTIVE"
        bump(advisor)
        return ok_object(ser_advisor(advisor), 200)
    if advisor["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, 409, "Advisor is not ACTIVE")
    # Atomic rehoming: simulate selector per ENROLLED advisee before any move.
    advisees = sort_records(students_of_advisor(aid, enrolled_only=True))
    counts = {a["id"]: active_caseload_count(a["id"])
              for a in stores["advisors"].values() if a["status"] == "ACTIVE" and a["id"] != aid}
    assignments = {}
    for s in advisees:
        pool = _selector_pool(exclude_id=aid, counts_override=counts)
        if not pool:
            fail(ERR_NO_ADVISOR_AVAILABLE, 409, "No advisor available to rehome an advisee")
        target, cnt = pool[0]
        assignments[s["id"]] = target["id"]
        counts[target["id"]] = cnt + 1
    for s in advisees:
        s["assigned_advisor_id"] = assignments[s["id"]]
        bump(s)
    advisor["status"] = "INACTIVE"
    bump(advisor)
    return ok_object(ser_advisor(advisor), 200)


@bp.post("/ccr/advisors/<aid>/reassignments")
def advisor_reassign(aid):
    body = get_body()
    validate_schema(body, {
        "student_ids": {"kind": "list", "required": True},
        "target_advisor_id": {"kind": "str", "required": True},
        "expected_advisor_version": {"kind": "int", "required": True},
    })
    require_role(g.user_role, "DistrictAdmin")
    source = _get_advisor(aid)
    # Body FK existence (stage 5) precedes the OCC check (stage 6).
    target = stores["advisors"].get(body["target_advisor_id"])
    if target is None:
        fail(ERR_NOT_FOUND, 404, "Target advisor not found")
    students = []
    for sid in body["student_ids"]:
        if not isinstance(sid, str):
            fail(ERR_VALIDATION, 400, "student_ids must be a list of ids")
        st = stores["students"].get(sid)
        if st is None:
            fail(ERR_NOT_FOUND, 404, "Student not found")
        students.append(st)
    if body["expected_advisor_version"] != source["version"]:
        fail(ERR_STALE_VERSION, 412, "expected_advisor_version is stale")
    for st in students:
        if st["assigned_advisor_id"] != aid or st["status"] != "ENROLLED":
            fail(ERR_INVALID_STATE, 409, "Student is not an ENROLLED advisee of this advisor")
    for st in students:
        st["assigned_advisor_id"] = target["id"]
        bump(st)
    bump(source)
    bump(target)
    return ok_object({
        "moved_count": len(students),
        "source_active_caseload_count": active_caseload_count(aid),
        "target_active_caseload_count": active_caseload_count(target["id"]),
    }, 200)


@bp.get("/ccr/advisors/<aid>/equity-report")
def advisor_equity(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    advisor = _get_advisor(aid)
    total_students, total_capacity = district_totals()
    cnt = active_caseload_count(aid)
    return ok_object({
        "advisor_id": aid,
        "active_caseload_count": cnt,
        "caseload_load_simple": cnt,
        "caseload_load_weighted": caseload_load_weighted(aid),
        "equity_gap_index": equity_gap_index(aid),
        "target_caseload": target_caseload(advisor),
        "district_total_students": total_students,
        "district_total_capacity": total_capacity,
    }, 200)


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------

@bp.post("/ccr/teachers")
def teacher_create():
    body = get_body()
    validate_schema(body, {
        "full_name": {"kind": "str", "required": True},
        "department": {"kind": "str", "required": True},
        "max_active_letters": {"kind": "int", "required": True, "min": 1},
    })
    require_role(g.user_role, "DistrictAdmin")
    rec = mint("teachers")
    rec.update({
        "full_name": body["full_name"],
        "department": body["department"],
        "max_active_letters": body["max_active_letters"],
        "status": "ACTIVE",
    })
    stores["teachers"][rec["id"]] = rec
    return ok_object(ser_teacher(rec), 201)


def _get_teacher(tid):
    t = stores["teachers"].get(tid)
    if t is None:
        fail(ERR_NOT_FOUND, 404, "Teacher not found")
    return t


@bp.get("/ccr/teachers/<tid>")
def teacher_get(tid):
    require_role(g.user_role, "DistrictAdmin", "Teacher")
    teacher = _get_teacher(tid)
    if g.user_role == "Teacher" and g.user_id != tid:
        fail(ERR_FORBIDDEN, 403, "Teacher may only read their own record")
    return ok_object(ser_teacher(teacher), 200)


@bp.patch("/ccr/teachers/<tid>")
def teacher_patch(tid):
    body = get_body()
    validate_schema(body, {
        "department": {"kind": "str", "required": False},
        "max_active_letters": {"kind": "int", "required": False, "min": 1},
        "status": {"kind": "str", "required": False, "choices": TEACHER_STATUSES},
    })
    require_role(g.user_role, "DistrictAdmin")
    teacher = _get_teacher(tid)
    if "department" in body and body["department"] is not None:
        teacher["department"] = body["department"]
    if "max_active_letters" in body and body["max_active_letters"] is not None:
        teacher["max_active_letters"] = body["max_active_letters"]
    if "status" in body and body["status"] is not None:
        teacher["status"] = body["status"]
    bump(teacher)
    return ok_object(ser_teacher(teacher), 200)


@bp.get("/ccr/teachers/<tid>/recommendation-requests")
def teacher_recs(tid):
    require_role(g.user_role, "DistrictAdmin", "Teacher")
    _get_teacher(tid)
    if g.user_role == "Teacher" and g.user_id != tid:
        fail(ERR_FORBIDDEN, 403, "Teacher may only read their own queue")
    items = [r for r in stores["rec_requests"].values() if r["teacher_id"] == tid]
    from flask import request
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    from computed import ser_rec_request
    return paginate(items, ser_rec_request)


# ---------------------------------------------------------------------------
# Pathways
# ---------------------------------------------------------------------------

@bp.post("/ccr/pathways")
def pathway_create():
    body = get_body()
    validate_schema(body, {
        "pathway_code": {"kind": "str", "required": True},
        "name": {"kind": "str", "required": True},
        "required_course_codes": {"kind": "list", "required": True},
        "required_certification_code": {"kind": "str", "required": False},
        "required_work_hours": {"kind": "int", "required": False, "min": 0},
    })
    require_role(g.user_role, "DistrictAdmin")
    if any(p["pathway_code"] == body["pathway_code"] for p in stores["pathways"].values()):
        fail(ERR_DUPLICATE_CODE, 409, "pathway_code already in use")
    codes = body["required_course_codes"]
    for c in codes:
        if not isinstance(c, str):
            fail(ERR_VALIDATION, 400, "required_course_codes must be strings")
    rec = mint("pathways")
    rec.update({
        "pathway_code": body["pathway_code"],
        "name": body["name"],
        "required_course_codes": list(codes),
        "required_certification_code": body.get("required_certification_code"),
        "required_work_hours": body.get("required_work_hours", 0) or 0,
        "status": "ACTIVE",
    })
    stores["pathways"][rec["id"]] = rec
    return ok_object(ser_pathway(rec), 201)


def _get_pathway(pid):
    p = stores["pathways"].get(pid)
    if p is None:
        fail(ERR_NOT_FOUND, 404, "Pathway not found")
    return p


@bp.get("/ccr/pathways/<pid>")
def pathway_get(pid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "WblCoordinator", "Teacher")
    return ok_object(ser_pathway(_get_pathway(pid)), 200)


@bp.patch("/ccr/pathways/<pid>")
def pathway_patch(pid):
    body = get_body()
    validate_schema(body, {
        "name": {"kind": "str", "required": False},
        "required_work_hours": {"kind": "int", "required": False, "min": 0},
        "status": {"kind": "str", "required": False, "choices": PATHWAY_STATUSES},
    })
    require_role(g.user_role, "DistrictAdmin")
    pathway = _get_pathway(pid)
    if "name" in body and body["name"] is not None:
        pathway["name"] = body["name"]
    if "required_work_hours" in body and body["required_work_hours"] is not None:
        pathway["required_work_hours"] = body["required_work_hours"]
    if "status" in body and body["status"] is not None:
        pathway["status"] = body["status"]
    bump(pathway)
    return ok_object(ser_pathway(pathway), 200)


@bp.get("/ccr/pathways/<pid>/plans")
def pathway_plans(pid):
    require_role(g.user_role, "DistrictAdmin", "Advisor")
    _get_pathway(pid)
    items = [p for p in stores["plans"].values() if p["pathway_id"] == pid]
    from computed import ser_plan
    return paginate(items, ser_plan)
