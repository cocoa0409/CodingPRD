"""Recommendation request routing (PRD §3.5)."""

from flask import Blueprint, g, request

from store import stores, mint, bump, now
from util import (
    ok_object, paginate, fail, get_body, validate_schema, require_role,
    parse_datetime,
    ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STUDENT_NOT_ENROLLED, ERR_CROSS_STUDENT_REFERENCE,
    ERR_DUE_DATE_PAST, ERR_TEACHER_CAPACITY_EXCEEDED,
    ERR_REQUEST_NOT_ROUTED_TO_YOU,
)
from computed import ser_rec_request, teacher_open_request_count
from routes.students import get_student_or_404, student_ownership

bp = Blueprint("recs", __name__)

REC_STATUSES = ("REQUESTED", "ACCEPTED", "DECLINED", "SUBMITTED", "VERIFIED", "WITHDRAWN")


def get_rec_or_404(rid):
    r = stores["rec_requests"].get(rid)
    if r is None:
        fail(ERR_NOT_FOUND, 404, "Recommendation request not found")
    return r


@bp.post("/ccr/students/<sid>/recommendation-requests")
def rec_create(sid):
    body = get_body()
    validate_schema(body, {
        "teacher_id": {"kind": "str", "required": True},
        "due_at": {"kind": "datetime", "required": True},
        "application_id": {"kind": "str", "required": False},
    })
    require_role(g.user_role, "Student")
    student = get_student_or_404(sid)
    teacher = stores["teachers"].get(body["teacher_id"])
    if teacher is None:
        fail(ERR_NOT_FOUND, 404, "Teacher not found")
    app = None
    if body.get("application_id") is not None:
        app = stores["applications"].get(body["application_id"])
        if app is None:
            fail(ERR_NOT_FOUND, 404, "Application not found")
    student_ownership(sid)
    # Clock-relative rule (stage 11) precedes cross-entity gates (stage 12).
    if parse_datetime(body["due_at"]) <= now():
        fail(ERR_DUE_DATE_PAST, 409, "due_at must be in the future")
    if student["status"] != "ENROLLED":
        fail(ERR_STUDENT_NOT_ENROLLED, 409, "Student is not ENROLLED")
    if teacher["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, 409, "Teacher is not ACTIVE")
    if app is not None and app["student_id"] != sid:
        fail(ERR_CROSS_STUDENT_REFERENCE, 409,
             "application_id belongs to a different student")
    # Capacity (stage 13): equality rejects.
    if teacher_open_request_count(teacher["id"]) >= teacher["max_active_letters"]:
        fail(ERR_TEACHER_CAPACITY_EXCEEDED, 409, "Teacher open-letter capacity reached")
    rec = mint("rec_requests")
    rec.update({
        "student_id": sid,
        "teacher_id": teacher["id"],
        "application_id": app["id"] if app is not None else None,
        "due_at": parse_datetime(body["due_at"]),
        "status": "REQUESTED",
        "reroute_count": 0,
        "submitted_at": None,
        "verified_at": None,
    })
    stores["rec_requests"][rec["id"]] = rec
    return ok_object(ser_rec_request(rec), 201)


@bp.get("/ccr/students/<sid>/recommendation-requests")
def rec_list_for_student(sid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "Teacher")
    get_student_or_404(sid)
    student_ownership(sid)
    items = [r for r in stores["rec_requests"].values() if r["student_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, ser_rec_request)


@bp.get("/ccr/recommendation-requests/<rid>")
def rec_get(rid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "Teacher")
    rec = get_rec_or_404(rid)
    if g.user_role == "Student":
        student_ownership(rec["student_id"])
    if g.user_role == "Teacher" and g.user_id != rec["teacher_id"]:
        fail(ERR_FORBIDDEN, 403, "Teacher may only read requests routed to them")
    return ok_object(ser_rec_request(rec), 200)


@bp.get("/ccr/applications/<aid>/recommendation-requests")
def rec_list_for_application(aid):
    require_role(g.user_role, "DistrictAdmin", "Advisor", "Student", "Teacher")
    app = stores["applications"].get(aid)
    if app is None:
        fail(ERR_NOT_FOUND, 404, "Application not found")
    if g.user_role == "Student":
        student_ownership(app["student_id"])
    items = [r for r in stores["rec_requests"].values() if r["application_id"] == aid]
    return paginate(items, ser_rec_request)


# Per-target roles for the letter routing machine (PRD §4 / §3.5).
_REC_TARGET_ROLES = {
    "ACCEPTED": ("Teacher",),
    "DECLINED": ("Teacher",),
    "SUBMITTED": ("Teacher",),
    "VERIFIED": ("Advisor",),
    "WITHDRAWN": ("Student",),
    "REQUESTED": ("Advisor",),
}

_REC_TRANSITIONS = {
    "ACCEPTED": ("REQUESTED",),
    "DECLINED": ("REQUESTED",),
    "SUBMITTED": ("ACCEPTED",),
    "VERIFIED": ("SUBMITTED",),
    "WITHDRAWN": ("REQUESTED", "ACCEPTED"),
    "REQUESTED": ("DECLINED",),  # reroute
}


@bp.post("/ccr/recommendation-requests/<rid>/transition")
def rec_transition(rid):
    body = get_body()
    validate_schema(body, {
        "to_status": {"kind": "str", "required": True, "choices": REC_STATUSES},
        "new_teacher_id": {"kind": "str", "required": False},
        "due_at": {"kind": "datetime", "required": False},
    })
    target = body["to_status"]
    # Reroute schema: new_teacher_id is required when to_status=REQUESTED.
    if target == "REQUESTED" and body.get("new_teacher_id") is None:
        fail("ERR_VALIDATION", 400, "new_teacher_id is required for reroute")
    require_role(g.user_role, "Student", "Teacher", "Advisor")
    require_role(g.user_role, *_REC_TARGET_ROLES[target])
    rec = get_rec_or_404(rid)
    # Body FK existence (stage 5) precedes ownership (7) and state (8).
    new_teacher = None
    if target == "REQUESTED":
        new_teacher = stores["teachers"].get(body["new_teacher_id"])
        if new_teacher is None:
            fail(ERR_NOT_FOUND, 404, "New teacher not found")
    # Ownership / context (stage 7).
    if g.user_role == "Teacher" and rec["teacher_id"] != g.user_id:
        fail(ERR_REQUEST_NOT_ROUTED_TO_YOU, 403, "Request is routed to another teacher")
    if target == "VERIFIED":
        student = stores["students"][rec["student_id"]]
        if student["assigned_advisor_id"] != g.user_id:
            fail(ERR_FORBIDDEN, 403, "Only the student's assigned advisor may verify")
    if target == "WITHDRAWN" and rec["student_id"] != g.user_id:
        fail(ERR_FORBIDDEN, 403, "Student may only withdraw their own requests")
    # State machine from-state (stage 8).
    if rec["status"] not in _REC_TRANSITIONS[target]:
        fail(ERR_INVALID_STATE, 409,
             f"Cannot move request from {rec['status']} to {target}")
    if target == "REQUESTED":
        # Reroute: clock rule (11) -> teacher ACTIVE (12) -> capacity (13).
        new_due = parse_datetime(body["due_at"]) if body.get("due_at") is not None else rec["due_at"]
        if new_due <= now():
            fail(ERR_DUE_DATE_PAST, 409, "due_at must be in the future")
        if new_teacher["status"] != "ACTIVE":
            fail(ERR_INVALID_STATE, 409, "New teacher is not ACTIVE")
        if teacher_open_request_count(new_teacher["id"]) >= new_teacher["max_active_letters"]:
            fail(ERR_TEACHER_CAPACITY_EXCEEDED, 409, "Teacher open-letter capacity reached")
        rec["teacher_id"] = new_teacher["id"]
        rec["due_at"] = new_due
        rec["reroute_count"] += 1
        rec["status"] = "REQUESTED"
        bump(rec)
        return ok_object(ser_rec_request(rec), 200)
    rec["status"] = target
    if target == "SUBMITTED":
        rec["submitted_at"] = now()
    if target == "VERIFIED":
        rec["verified_at"] = now()
    bump(rec)
    return ok_object(ser_rec_request(rec), 200)
