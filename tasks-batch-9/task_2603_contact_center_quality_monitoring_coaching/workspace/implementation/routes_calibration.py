"""Calibration sessions and submissions (PRD 3.7)."""
from flask import Blueprint

import calc
import derive
import scoring
import shape
from common import (body, created, fail, get, new_row, ok, ok_list, require,
                    rows, sorted_rows, touch)
from authz import actor, endpoint
from listing import page
from serial import view, views

bp = Blueprint("calibration", __name__)

SESSION_STATUSES = ("OPEN", "SCORING", "CLOSED_ALIGNED", "CLOSED_VARIANT", "VOID")
ALIGNMENTS = ("ALIGNED", "MINOR_VARIANCE", "MAJOR_VARIANCE")
CONSENT_OK = ("VERIFIED", "NOT_REQUIRED")
READ_ROLES = ("QualityManager", "QualityEvaluator", "Supervisor", "ComplianceAuditor")


def consent_gate(interaction):
    if interaction is None or interaction["recording_consent_status"] not in CONSENT_OK:
        fail("ERR_CONSENT_NOT_VERIFIED",
             "the interaction's recording consent is not VERIFIED or NOT_REQUIRED")


@bp.post("/calibration-sessions")
@endpoint("QualityManager")
def create_session():
    payload = body()
    form_id = shape.want_string(payload, "form_id")
    interaction_id = shape.want_string(payload, "interaction_id")
    start_raw, start = shape.want_datetime(payload, "scheduled_start")
    end_raw, end = shape.want_datetime(payload, "scheduled_end")
    scores = shape.want_item_scores(payload, "benchmark_item_scores")

    form = require("forms", form_id, "ERR_FORM_NOT_FOUND")
    interaction = require("interactions", interaction_id, "ERR_INTERACTION_NOT_FOUND")

    if form["status"] != "ACTIVE":
        fail("ERR_FORM_NOT_ACTIVE", "a calibration session needs an ACTIVE form")

    consent_gate(interaction)

    behaviors = calc.form_behaviors(form["id"])
    scoring.validate_item_scores(behaviors, scores)

    if not end > start:
        fail("ERR_INVALID_TIME_RANGE",
             "scheduled_end must be strictly after scheduled_start")

    benchmark = calc.renormalized_score(form, behaviors, scores)

    session = new_row("sessions", {
        "form_id": form["id"],
        "interaction_id": interaction["id"],
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "benchmark_item_scores": dict(scores),
        "benchmark_weighted_score": benchmark,
        "status": "OPEN",
        "participant_count": 0,
        "variance_pct": None,
        "mean_abs_deviation": None,
        "guidance_updates_applied": 0,
    })
    return created(view(session))


@bp.post("/calibration-sessions/<session_id>/start-scoring")
@endpoint("QualityManager")
def start_scoring(session_id):
    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    if session["status"] != "OPEN":
        fail("ERR_SESSION_NOT_OPEN", "only an OPEN session may move to SCORING")
    form = get("forms", session["form_id"])
    if form is None or form["status"] != "ACTIVE":
        fail("ERR_FORM_NOT_ACTIVE", "the session's form is no longer ACTIVE")
    derive.force(session, {"status": "SCORING"})
    return ok(view(session))


@bp.post("/calibration-submissions")
@endpoint("QualityEvaluator")
def create_submission():
    payload = body()
    session_id = shape.want_string(payload, "session_id")
    scores = shape.want_item_scores(payload, "item_scores")

    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    if session["status"] != "SCORING":
        fail("ERR_SESSION_NOT_SCORING", "submissions are accepted only in SCORING")

    form = get("forms", session["form_id"])
    behaviors = calc.form_behaviors(session["form_id"])
    scoring.validate_item_scores(behaviors, scores)

    for other in rows("submissions"):
        if other["session_id"] == session["id"] and other["evaluator_id"] == actor():
            fail("ERR_SESSION_PARTICIPANT_DUPLICATE",
                 "this evaluator has already submitted to the session")

    submission = new_row("submissions", {
        "session_id": session["id"],
        "evaluator_id": actor(),
        "item_scores": dict(scores),
        "weighted_score": calc.renormalized_score(form, behaviors, scores),
        "deviation_pct": None,
        "alignment": None,
    }, common=False)
    derive.force(session, {
        "participant_count": len(calc.session_submissions(session["id"])),
    })
    return created(view(submission))


def _guidance_entries(payload):
    raw = shape.opt(payload, "guidance_updates")
    if raw is None:
        return []
    if not isinstance(raw, list):
        shape.bad("field 'guidance_updates' must be an array")
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            shape.bad("each 'guidance_updates' entry must be an object")
        code = shape.want_string(item, "code")
        text = shape.want_string(item, "guidance_text")
        entries.append((code, text))
    return entries


@bp.post("/calibration-sessions/<session_id>/close")
@endpoint("QualityManager")
def close_session(session_id):
    payload = body()
    entries = _guidance_entries(payload)

    session = require("sessions", session_id, "ERR_SESSION_NOT_FOUND")
    if session["status"] != "SCORING":
        fail("ERR_SESSION_NOT_SCORING", "only a SCORING session may be closed")

    info = calc.calibration_variance(session)

    # A VOID close is the deliberate no-op (PRD 3.7).
    if info["outcome"] == "VOID":
        derive.force(session, {
            "status": "VOID",
            "participant_count": info["participant_count"],
            "variance_pct": None,
            "mean_abs_deviation": None,
            "guidance_updates_applied": 0,
        })
        return ok(view(session))

    pending = {}
    order = []

    # STEP ONE -- score every submission and refresh each evaluator's deviation.
    for (submission, deviation, alignment) in info["details"]:
        submission["deviation_pct"] = deviation
        submission["alignment"] = alignment
        evaluator_id = submission["evaluator_id"]
        if evaluator_id not in pending:
            pending[evaluator_id] = {}
            order.append(evaluator_id)
        pending[evaluator_id]["last_deviation_pct"] = deviation

    # STEP TWO -- the session's own figures.
    derive.force(session, {
        "status": info["outcome"],
        "participant_count": info["participant_count"],
        "variance_pct": info["variance_pct"],
        "mean_abs_deviation": info["mean_abs_deviation"],
        "guidance_updates_applied": len(entries),
    })

    # STEP THREE -- evaluator standing, in created_at ascending order.
    suspended = []
    for (submission, deviation, alignment) in info["details"]:
        evaluator = get("evaluators", submission["evaluator_id"])
        if evaluator is None:
            continue
        current = evaluator["calibration_status"]
        nxt = calc.next_calibration_status(current, deviation, alignment)
        if nxt != current:
            pending[evaluator["id"]]["calibration_status"] = nxt
            if nxt == "SUSPENDED":
                suspended.append(evaluator["id"])

    # STEP FOUR -- guidance rewrites and the single form-level bump.
    if entries:
        behaviors = {b["code"]: b for b in calc.form_behaviors(session["form_id"])}
        for (code, text) in entries:
            behavior = behaviors.get(code)
            if behavior is None:
                continue
            behavior["guidance_text"] = text
            behavior["guidance_version"] = int(behavior["guidance_version"]) + 1
            touch(behavior)
        form = get("forms", session["form_id"])
        if form is not None:
            derive.force(form, {"guidance_version": int(form["guidance_version"]) + 1})

    # CLOSED_VARIANT hops one and two -- release the stranded assignments.
    for evaluator_id in suspended:
        for selection in sorted_rows(rows("selections")):
            if (selection.get("assigned_evaluator_id") != evaluator_id
                    or selection["status"] != "ASSIGNED"):
                continue
            if derive.selection_has_evaluation(selection["id"]):
                continue
            selection["status"] = "SELECTED"
            selection["assigned_evaluator_id"] = None
            selection["review_window_start"] = None
            selection["review_window_end"] = None
            touch(selection)

    for evaluator_id in order:
        evaluator = get("evaluators", evaluator_id)
        if evaluator is None:
            continue
        updates = dict(pending[evaluator_id])
        updates["open_assignment_count"] = calc.open_assignment_count(evaluator_id)
        derive.force(evaluator, updates)

    return ok(view(session))


@bp.get("/calibration-sessions/<session_id>")
@endpoint(*READ_ROLES)
def read_session(session_id):
    return ok(view(require("sessions", session_id, "ERR_SESSION_NOT_FOUND")))


@bp.get("/calibration-sessions")
@endpoint(*READ_ROLES)
def list_sessions():
    limit, offset = shape.pagination()
    form_id = shape.query_str("form_id")
    interaction_id = shape.query_str("interaction_id")
    status = shape.query_enum("status", SESSION_STATUSES)
    items = sorted_rows(rows("sessions"))
    if form_id is not None:
        items = [s for s in items if s["form_id"] == form_id]
    if interaction_id is not None:
        items = [s for s in items if s["interaction_id"] == interaction_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)


@bp.get("/calibration-submissions/<submission_id>")
@endpoint(*READ_ROLES)
def read_submission(submission_id):
    return ok(view(require("submissions", submission_id, "ERR_SUBMISSION_NOT_FOUND")))


@bp.get("/calibration-submissions")
@endpoint(*READ_ROLES)
def list_submissions():
    limit, offset = shape.pagination()
    session_id = shape.query_str("session_id")
    evaluator_id = shape.query_str("evaluator_id")
    alignment = shape.query_enum("alignment", ALIGNMENTS)
    items = sorted_rows(rows("submissions"))
    if session_id is not None:
        items = [s for s in items if s["session_id"] == session_id]
    if evaluator_id is not None:
        items = [s for s in items if s["evaluator_id"] == evaluator_id]
    if alignment is not None:
        items = [s for s in items if s.get("alignment") == alignment]
    window, total = page(items, limit, offset)
    return ok_list(views(window), limit, offset, total)
