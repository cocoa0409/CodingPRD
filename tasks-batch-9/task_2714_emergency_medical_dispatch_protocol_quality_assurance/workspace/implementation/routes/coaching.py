"""Coaching plans, retraining delivery and the remediation hours ledger.

PRD 3.8.  Every hours figure here is a full recomputation over source sessions,
which is what lets a cancellation of an already-completed session return the
plan and the dispatcher to exactly their pre-completion values.
"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
import helpers
import validate
from auth import require
from cascades import set_fields
from envelope import ok, public
from errors import fail
from store import base_row, clock, db, order_rows, touch

bp = Blueprint("coaching", __name__)

SEVERITIES = ("ADVISORY", "STANDARD", "CRITICAL")
FOCUS_AREAS = (
    "CASE_ENTRY",
    "KEY_QUESTIONS",
    "PRE_ARRIVAL_INSTRUCTIONS",
    "FINAL_CODING",
    "DETERMINANT_CODING",
    "DACPR",
)
MODALITIES = ("CLASSROOM", "SIMULATION", "ONLINE", "ONE_ON_ONE")
TRAINABLE_STATUSES = ("APPROVED", "ACTIVE")
OPEN_PLAN_STATES = ("ASSIGNED", "IN_PROGRESS")
SESSION_BUFFER = timedelta(minutes=45)


@bp.post("/coaching-plans")
@require("QaSupervisor")
def create_plan():
    payload = validate.body()
    dispatcher_id = validate.get_str(payload, "dispatcher_id")
    severity = validate.get_enum(payload, "severity", SEVERITIES)
    focus = validate.get_enum(payload, "focus_area", FOCUS_AREAS)
    expected_version = validate.get_int(
        payload, "expected_dispatcher_version", minimum=0
    )
    due_at = validate.get_instant(payload, "due_at", required=False)
    source_review_id = validate.get_str(payload, "source_review_id", required=False)

    dispatcher = helpers.dispatcher(dispatcher_id)
    review = None
    if source_review_id is not None:
        review = helpers.review(source_review_id)

    if expected_version != dispatcher["version"]:
        fail(
            "ERR_STALE_DISPATCHER_VERSION",
            "expected_dispatcher_version does not match the dispatcher's version.",
        )

    if review is not None and cascades.find_auto_plan(
        dispatcher["id"], review["id"]
    ) is not None:
        fail(
            "ERR_DUPLICATE_COACHING_PLAN",
            "An automatic plan already exists on this dispatcher and review.",
        )

    # A manual create is a deliberate reset: everything still open is superseded.
    for plan in order_rows(cascades.plans_of_dispatcher(dispatcher["id"])):
        if plan["status"] in cascades.OPEN_PLAN_STATES:
            set_fields(
                plan, {"status": "CANCELLED", "closure_reason": "SUPERSEDED"}
            )

    plan = base_row()
    plan.update(
        {
            "dispatcher_id": dispatcher["id"],
            "origin": "MANUAL",
            "severity": severity,
            "severity_rank": calc.SEVERITY_RANK[severity],
            "focus_area": focus,
            "source_review_id": review["id"] if review is not None else None,
            "required_hours": calc.q1(calc.REQUIRED_HOURS[severity]),
            "credited_hours": calc.q2(Decimal("0")),
            "status": "ASSIGNED",
            "closure_reason": None,
            "due_at": due_at,
            "verified_at": None,
        }
    )
    db.coaching_plans[plan["id"]] = plan

    cascades.recompute_hours_and_privilege(dispatcher)
    # The optimistic-concurrency token must move on a manual create even when
    # the recomputed ledger happens to land on the same numbers (PRD 3.8).
    touch(dispatcher)
    return ok(public(plan), 201)


@bp.get("/coaching-plans/<plan_id>")
@require("ProgramAdmin", "QaSupervisor", "QaReviewer", "MedicalDirector", "Dispatcher")
def read_plan(plan_id):
    return ok(public(helpers.coaching_plan(plan_id)))


@bp.get("/coaching-plans")
@require("ProgramAdmin", "QaSupervisor", "QaReviewer", "MedicalDirector")
def list_plans():
    limit, offset = validate.pagination()
    filters = {
        "dispatcher_id": request.args.get("dispatcher_id"),
        "source_review_id": request.args.get("source_review_id"),
        "status": request.args.get("status"),
        "severity": request.args.get("severity"),
        "origin": request.args.get("origin"),
    }
    rows = [p for p in db.coaching_plans.values() if helpers.matches(p, filters)]
    return helpers.respond_list(rows, limit, offset)


def _windows_touch(new_start, new_end, other_start, other_end):
    """Closed comparison of the buffered new window against an existing one."""
    return new_start - SESSION_BUFFER <= other_end and other_start <= new_end + SESSION_BUFFER


@bp.post("/coaching-plans/<plan_id>/retraining-sessions")
@require("QaSupervisor")
def schedule_session(plan_id):
    payload = validate.body()
    version_id = validate.get_str(payload, "protocol_version_id")
    starts_at = validate.get_instant(payload, "starts_at")
    ends_at = validate.get_instant(payload, "ends_at")
    modality = validate.get_enum(payload, "modality", MODALITIES)

    plan = helpers.coaching_plan(plan_id)
    version = helpers.protocol_version(version_id)
    dispatcher = db.dispatchers.get(plan["dispatcher_id"])

    if dispatcher is not None and version["program_id"] != dispatcher["program_id"]:
        fail(
            "ERR_PROGRAM_SCOPE_MISMATCH",
            "The curriculum version belongs to a different programme.",
        )
    if version["status"] not in TRAINABLE_STATUSES:
        fail(
            "ERR_CURRICULUM_VERSION_NOT_TRAINABLE",
            "Only an approved or active version may be taught.",
        )
    if plan["status"] not in OPEN_PLAN_STATES:
        fail("ERR_PLAN_NOT_OPEN", "This coaching plan is not open for scheduling.")
    if ends_at <= starts_at:
        fail("ERR_INVALID_TIME_WINDOW", "ends_at must be strictly after starts_at.")

    if dispatcher is not None:
        for other in order_rows(cascades.sessions_of_dispatcher(dispatcher["id"])):
            if other["status"] not in ("SCHEDULED", "COMPLETED"):
                continue
            if _windows_touch(
                starts_at, ends_at, other["starts_at"], other["ends_at"]
            ):
                fail(
                    "ERR_SESSION_WINDOW_OVERLAP",
                    "The dispatcher is already booked inside the 45-minute buffer.",
                )

    seconds = Decimal((ends_at - starts_at).total_seconds())
    session = base_row()
    session.update(
        {
            "coaching_plan_id": plan["id"],
            "protocol_version_id": version["id"],
            "starts_at": starts_at,
            "ends_at": ends_at,
            "modality": modality,
            "duration_hours": calc.q2(seconds / Decimal("3600")),
            "status": "SCHEDULED",
            "attendance_confirmed": None,
            "cancel_reason": None,
            "completed_at": None,
        }
    )
    db.sessions[session["id"]] = session

    if plan["status"] == "ASSIGNED":
        set_fields(plan, {"status": "IN_PROGRESS"})
    return ok(public(session), 201)


@bp.get("/coaching-plans/<plan_id>/retraining-sessions")
@require("ProgramAdmin", "QaSupervisor", "QaReviewer", "MedicalDirector", "Dispatcher")
def list_sessions(plan_id):
    limit, offset = validate.pagination()
    plan = helpers.coaching_plan(plan_id)
    filters = {"status": request.args.get("status")}
    rows = [
        s
        for s in cascades.sessions_of_plan(plan["id"])
        if helpers.matches(s, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


def _settle_plan(plan):
    """Recompute credited hours and cycle the plan across the VERIFIED line."""
    cascades.recompute_plan_credited_hours(plan)
    if plan["credited_hours"] >= plan["required_hours"]:
        if plan["status"] == "IN_PROGRESS":
            set_fields(plan, {"status": "VERIFIED", "verified_at": clock()})
    elif plan["status"] == "VERIFIED":
        set_fields(plan, {"status": "IN_PROGRESS", "verified_at": None})
    dispatcher = db.dispatchers.get(plan["dispatcher_id"])
    if dispatcher is not None:
        cascades.recompute_hours_and_privilege(dispatcher)


@bp.post("/retraining-sessions/<session_id>/complete")
@require("QaSupervisor")
def complete_session(session_id):
    payload = validate.body()
    confirmed = validate.get_bool(payload, "attendance_confirmed")
    if confirmed is not True:
        fail(
            "ERR_INVALID_REQUEST",
            "attendance_confirmed must be true to complete a session.",
        )

    session = helpers.retraining_session(session_id)

    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_NOT_COMPLETABLE", "Only a scheduled session may complete.")
    plan = db.coaching_plans.get(session["coaching_plan_id"])
    if plan is None or plan["status"] not in OPEN_PLAN_STATES:
        fail("ERR_PLAN_NOT_OPEN", "The session's coaching plan is not open.")
    if clock() < session["ends_at"]:
        fail("ERR_SESSION_NOT_COMPLETABLE", "The session has not ended yet.")

    set_fields(
        session,
        {
            "attendance_confirmed": True,
            "status": "COMPLETED",
            "completed_at": clock(),
        },
    )
    _settle_plan(plan)
    return ok(public(session))


@bp.post("/retraining-sessions/<session_id>/cancel")
@require("QaSupervisor")
def cancel_session(session_id):
    payload = validate.body()
    reason = validate.get_str(payload, "cancel_reason")

    session = helpers.retraining_session(session_id)

    if session["status"] == "CANCELLED":
        fail("ERR_SESSION_NOT_CANCELLABLE", "This session is already cancelled.")

    was_completed = session["status"] == "COMPLETED"
    set_fields(
        session,
        {"status": "CANCELLED", "cancel_reason": reason, "completed_at": None},
    )
    plan = db.coaching_plans.get(session["coaching_plan_id"])
    if plan is not None and was_completed:
        # A compensating action: the credited hours go back to their old value.
        _settle_plan(plan)
    return ok(public(session))
