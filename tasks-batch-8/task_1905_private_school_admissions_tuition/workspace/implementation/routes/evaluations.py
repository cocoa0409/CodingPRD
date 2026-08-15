"""Entrance evaluation and test session routes."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, get_json_body, check_fields
from response import success, success_list
from services import serializers as ser
from services.helpers import (make_record, get_or_404, ref_or_404, sort_created)
from services.lifecycle import maybe_complete_evaluation, touch

bp = Blueprint("evaluations", __name__)

STAFF_ROLES = ("AdmissionDirector", "AdmissionOfficer", "FinancialAidOfficer")


def _validate_eval_window(vals):
    if vals["scheduled_end"] <= vals["scheduled_start"]:
        raise errors.err(errors.ERR_VALIDATION,
                         "scheduled_end must be strictly after scheduled_start")


def _check_interviewer_conflict(interviewer_id, start, end, exclude_id=None):
    """Half-open interval overlap [start, end); adjacency allowed."""
    for e in db.evaluations.values():
        if e["kind"] != "INTERVIEW" or e["status"] == "CANCELLED":
            continue
        if e["interviewer_id"] != interviewer_id or e["id"] == exclude_id:
            continue
        e_start = db.parse_iso(e["scheduled_start"])
        e_end = db.parse_iso(e["scheduled_end"])
        if start < e_end and e_start < end:
            raise errors.err(errors.ERR_INTERVIEWER_SCHEDULE_CONFLICT,
                             "Interviewer has a conflicting interview window")


def _check_test_session(session, start, end, exclude_id=None):
    """Session window containment then aggregate capacity."""
    s_start = db.parse_iso(session["session_start"])
    s_end = db.parse_iso(session["session_end"])
    if start < s_start or end > s_end:
        raise errors.err(errors.ERR_EVALUATION_OUTSIDE_SESSION,
                         "TEST evaluation window must lie within its session window")
    booked = 0
    for e in db.evaluations.values():
        if (e["kind"] == "TEST" and e["test_session_id"] == session["id"]
                and e["status"] != "CANCELLED" and e["id"] != exclude_id):
            booked += 1
    if booked >= session["room_capacity"]:
        raise errors.err(errors.ERR_TEST_SESSION_FULL,
                         "Test session already holds room_capacity non-cancelled tests")


@bp.post("/admissions/evaluations")
@require_roles("AdmissionOfficer")
def create_evaluation(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "application_id": "string",
        "kind": ("enum", ("TEST", "INTERVIEW")),
        "scheduled_start": "datetime",
        "scheduled_end": "datetime",
    }, {"interviewer_id": "string", "test_session_id": "string"})
    kind = vals["kind"]
    interviewer = vals.get("interviewer_id")
    session_id = vals.get("test_session_id")
    # Kind-specific field presence (layer 6)
    if kind == "INTERVIEW":
        if not interviewer:
            raise errors.err(errors.ERR_VALIDATION,
                             "INTERVIEW evaluations require interviewer_id")
        if session_id is not None:
            raise errors.err(errors.ERR_VALIDATION,
                             "INTERVIEW evaluations forbid test_session_id")
    else:
        if not session_id:
            raise errors.err(errors.ERR_VALIDATION,
                             "TEST evaluations require test_session_id")
        if interviewer is not None:
            raise errors.err(errors.ERR_VALIDATION,
                             "TEST evaluations forbid interviewer_id")
    _validate_eval_window(vals)

    # Body FK existence (layer 8)
    app = ref_or_404(db.applications, vals["application_id"], "Application")
    session = None
    if kind == "TEST":
        session = ref_or_404(db.test_sessions, session_id, "TestSession")

    # State / constraint / cross-entity checks
    if app["status"] in ser.APP_TERMINAL:
        raise errors.err(errors.ERR_APPLICATION_TERMINAL,
                         "The application is in a terminal state")
    if app["status"] not in ("SUBMITTED", "EVALUATION_COMPLETE"):
        raise errors.err(errors.ERR_APPLICATION_NOT_SUBMITTED,
                         "The application must be SUBMITTED or EVALUATION_COMPLETE")
    cycle = db.cycles[app["cycle_id"]]
    if cycle["status"] not in ("OPEN", "EARLY_CLOSED"):
        raise errors.err(errors.ERR_CYCLE_NOT_OPEN,
                         "The application's cycle is not in an admitting status")
    for e in db.evaluations.values():
        if (e["application_id"] == app["id"] and e["kind"] == kind
                and e["status"] != "CANCELLED"):
            raise errors.err(errors.ERR_DUPLICATE_EVALUATION_KIND,
                             "A non-cancelled evaluation of this kind already exists")
    if kind == "INTERVIEW":
        _check_interviewer_conflict(interviewer, vals["scheduled_start"],
                                    vals["scheduled_end"])
    else:
        _check_test_session(session, vals["scheduled_start"], vals["scheduled_end"])

    ev = make_record(db.evaluations, {
        "application_id": app["id"],
        "kind": kind,
        "scheduled_start": db.fmt_clock(vals["scheduled_start"]),
        "scheduled_end": db.fmt_clock(vals["scheduled_end"]),
        "interviewer_id": interviewer if kind == "INTERVIEW" else None,
        "test_session_id": session_id if kind == "TEST" else None,
        "score": None,
        "status": "SCHEDULED",
    })
    return success(ser.evaluation_view(ev), 201)


@bp.patch("/admissions/evaluations/<evaluationId>")
@require_roles("AdmissionOfficer")
def reschedule_evaluation(evaluationId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "expected_evaluation_version": "int",
    }, {
        "scheduled_start": "datetime",
        "scheduled_end": "datetime",
        "interviewer_id": "string",
        "test_session_id": "string",
    })
    ev = get_or_404(db.evaluations, evaluationId, "EntranceEvaluation")
    if vals["expected_evaluation_version"] != ev["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_evaluation_version does not match the evaluation's current version")
    if ev["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_EVALUATION_NOT_SCHEDULED,
                         "Reschedule requires the evaluation to be SCHEDULED")

    start = vals.get("scheduled_start")
    end = vals.get("scheduled_end")
    new_start = start if start is not None else db.parse_iso(ev["scheduled_start"])
    new_end = end if end is not None else db.parse_iso(ev["scheduled_end"])
    if new_end <= new_start:
        raise errors.err(errors.ERR_VALIDATION,
                         "scheduled_end must be strictly after scheduled_start")

    if ev["kind"] == "INTERVIEW":
        if "test_session_id" in vals and vals["test_session_id"] is not None:
            raise errors.err(errors.ERR_VALIDATION,
                             "INTERVIEW evaluations forbid test_session_id")
        interviewer = vals.get("interviewer_id", ev["interviewer_id"])
        if not interviewer:
            raise errors.err(errors.ERR_VALIDATION,
                             "INTERVIEW evaluations require interviewer_id")
        _check_interviewer_conflict(interviewer, new_start, new_end, exclude_id=ev["id"])
        ev["interviewer_id"] = interviewer
    else:  # TEST
        if "interviewer_id" in vals and vals["interviewer_id"] is not None:
            raise errors.err(errors.ERR_VALIDATION,
                             "TEST evaluations forbid interviewer_id")
        session_id = vals.get("test_session_id", ev["test_session_id"])
        session = ref_or_404(db.test_sessions, session_id, "TestSession")
        _check_test_session(session, new_start, new_end, exclude_id=ev["id"])
        ev["test_session_id"] = session_id

    ev["scheduled_start"] = db.fmt_clock(new_start)
    ev["scheduled_end"] = db.fmt_clock(new_end)
    touch(ev)
    return success(ser.evaluation_view(ev))


@bp.post("/admissions/evaluations/<evaluationId>/score")
@require_roles("AdmissionOfficer")
def score_evaluation(evaluationId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"score": "int"}, {})
    score = vals["score"]
    if score < 0 or score > 100:
        raise errors.err(errors.ERR_VALIDATION, "score must be an integer 0..100")
    ev = get_or_404(db.evaluations, evaluationId, "EntranceEvaluation")
    if ev["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_EVALUATION_NOT_SCHEDULED,
                         "Score requires the evaluation to be SCHEDULED")
    ev["score"] = score
    ev["status"] = "SCORED"
    touch(ev)
    app = db.applications[ev["application_id"]]
    maybe_complete_evaluation(app)
    return success(ser.evaluation_view(ev))


@bp.post("/admissions/evaluations/<evaluationId>/cancel")
@require_roles("AdmissionOfficer")
def cancel_evaluation(evaluationId, _uid, _role):
    ev = get_or_404(db.evaluations, evaluationId, "EntranceEvaluation")
    if ev["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_EVALUATION_NOT_SCHEDULED,
                         "Cancel requires the evaluation to be SCHEDULED")
    ev["status"] = "CANCELLED"
    touch(ev)
    return success(ser.evaluation_view(ev))


@bp.get("/admissions/evaluations")
@require_roles(*STAFF_ROLES)
def list_evaluations(_uid, _role):
    application_id = request.args.get("application_id")
    interviewer_id = request.args.get("interviewer_id")
    session_id = request.args.get("test_session_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = [e for e in db.evaluations.values()
             if (application_id is None or e["application_id"] == application_id)
             and (interviewer_id is None or e["interviewer_id"] == interviewer_id)
             and (session_id is None or e["test_session_id"] == session_id)
             and (kind is None or e["kind"] == kind)
             and (status is None or e["status"] == status)]
    return success_list([ser.evaluation_view(e) for e in sort_created(items)])


@bp.get("/admissions/evaluations/<evaluationId>")
@require_roles(*STAFF_ROLES)
def get_evaluation(evaluationId, _uid, _role):
    ev = get_or_404(db.evaluations, evaluationId, "EntranceEvaluation")
    return success(ser.evaluation_view(ev))


# --- Test sessions ----------------------------------------------------------

@bp.post("/admissions/test-sessions")
@require_roles("AdmissionDirector", "AdmissionOfficer")
def create_test_session(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "cycle_id": "string",
        "session_start": "datetime",
        "session_end": "datetime",
        "room_capacity": "int_pos",
    }, {})
    if vals["session_end"] <= vals["session_start"]:
        raise errors.err(errors.ERR_VALIDATION,
                         "session_end must be strictly after session_start")
    cycle = ref_or_404(db.cycles, vals["cycle_id"], "AdmissionCycle")
    session = make_record(db.test_sessions, {
        "cycle_id": cycle["id"],
        "session_start": db.fmt_clock(vals["session_start"]),
        "session_end": db.fmt_clock(vals["session_end"]),
        "room_capacity": vals["room_capacity"],
    })
    return success(ser.test_session_view(session), 201)


@bp.get("/admissions/test-sessions")
@require_roles(*STAFF_ROLES)
def list_test_sessions(_uid, _role):
    cycle_id = request.args.get("cycle_id")
    items = [t for t in db.test_sessions.values()
             if cycle_id is None or t["cycle_id"] == cycle_id]
    return success_list([ser.test_session_view(t) for t in sort_created(items)])


@bp.get("/admissions/test-sessions/<sessionId>")
@require_roles(*STAFF_ROLES)
def get_test_session(sessionId, _uid, _role):
    session = get_or_404(db.test_sessions, sessionId, "TestSession")
    return success(ser.test_session_view(session))
