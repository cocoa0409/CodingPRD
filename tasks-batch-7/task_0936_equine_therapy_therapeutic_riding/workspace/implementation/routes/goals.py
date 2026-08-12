"""Goals, progress notes and the staleness sweep (PRD §3.7)."""

from flask import Blueprint, request

from core import timeutil as T
from core.constants import (
    GOAL_MAX_RATING,
    GOAL_MET_CONSECUTIVE_HITS,
    GOAL_MIN_RATING,
    GOAL_STALE_AFTER_DAYS,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, caller_id, caller_role, endpoint, pagination, paginate, query_enum,
    validate_body,
)
from core.lookups import resource_or_404, rider_or_404, session_or_404
from core.constants import GOAL_DOMAINS
from core.store import all_rows, clock, db, new_row, touch
from domain import derive, gates, serialize

bp = Blueprint("goals", __name__)

GOAL_STATUSES = ["ACTIVE", "MET", "STALE", "DISCONTINUED"]
NOTE_STATUSES = ["DRAFT", "FINALIZED", "AMENDED"]


def _stale_after(goal):
    anchor = goal.get("last_rated_at") or goal["created_at"]
    return T.plus_days(anchor.dt, GOAL_STALE_AFTER_DAYS)


@bp.post("/riders/<rider_id>/goals")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def create_goal(rider_id):
    def cross(payload):
        if payload.get("target_rating") is not None \
                and payload.get("baseline_rating") is not None \
                and payload["target_rating"] <= payload["baseline_rating"]:
            fail("ERR_VALIDATION", "target_rating must exceed baseline_rating.")

    payload = validate_body([
        Field("domain", "enum", required=True, members=GOAL_DOMAINS),
        Field("objective", "string", required=True),
        Field("baseline_rating", "int", required=True,
              minimum=GOAL_MIN_RATING, maximum=GOAL_MAX_RATING),
        Field("target_rating", "int", required=True,
              minimum=GOAL_MIN_RATING, maximum=GOAL_MAX_RATING),
    ], cross=cross)
    rider_or_404(rider_id)
    row = new_row("goals")
    row.update({
        "rider_id": rider_id,
        "domain": payload["domain"],
        "objective": payload["objective"],
        "baseline_rating": payload["baseline_rating"],
        "target_rating": payload["target_rating"],
        "current_rating": None,
        "consecutive_target_hits": 0,
        "last_rated_at": None,
        "status": "ACTIVE",
        "discontinue_reason": None,
    })
    return object_response(serialize.goal(row), 201)


@bp.get("/goals")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def list_goals():
    limit, offset = pagination()
    status = query_enum("status", GOAL_STATUSES)
    domain = query_enum("domain", GOAL_DOMAINS)
    rider_id = request.args.get("rider_id")
    rows = all_rows("goals")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if domain is not None:
        rows = [r for r in rows if r["domain"] == domain]
    page = paginate(rows, limit, offset)
    return list_response([serialize.goal(r) for r in page], limit, offset, len(rows))


@bp.get("/goals/<goal_id>")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def read_goal(goal_id):
    return object_response(serialize.goal(resource_or_404("goals", goal_id)))


@bp.post("/goals/<goal_id>/discontinue")
@endpoint(["Instructor", "ProgramAdmin"])
def discontinue_goal(goal_id):
    payload = validate_body([Field("reason", "string", required=True)])
    row = resource_or_404("goals", goal_id)
    if row["status"] not in ("ACTIVE", "MET", "STALE"):
        fail("ERR_INVALID_STATE", "That goal is already discontinued.")
    row["status"] = "DISCONTINUED"
    row["discontinue_reason"] = payload["reason"]
    touch(row)
    return object_response(serialize.goal(row))


@bp.post("/goals/<goal_id>/reopen")
@endpoint(["Instructor", "ProgramAdmin"])
def reopen_goal(goal_id):
    # `reason` is required in the body, and no field on the goal preserves it.
    validate_body([Field("reason", "string", required=True)])
    row = resource_or_404("goals", goal_id)
    if row["status"] != "MET":
        fail("ERR_INVALID_STATE", "Only a MET goal may be reopened.")
    row["status"] = "ACTIVE"
    row["consecutive_target_hits"] = 0
    touch(row)
    return object_response(serialize.goal(row))


@bp.post("/_ops/goal-staleness-sweep")
@endpoint(["ProgramAdmin"])
def goal_staleness_sweep():
    now = clock.now()
    swept = []
    for goal in all_rows("goals"):
        if goal["status"] != "ACTIVE":
            continue
        if now >= _stale_after(goal):
            goal["status"] = "STALE"
            touch(goal)
            swept.append(goal)
    return object_response({
        "swept_count": len(swept),
        "stale_goal_ids": [g["id"] for g in swept],
        "evaluated_at": clock.stamp().raw,
    })


# ------------------------------------------------------------ progress notes
@bp.post("/sessions/<session_id>/progress-notes")
@endpoint(["Instructor"])
def draft_note(session_id):
    def cross(payload):
        entries = payload.get("goal_ratings")
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                fail("ERR_VALIDATION", "Each goal_ratings entry must be an object.")
            if "goal_id" not in entry or entry["goal_id"] is None:
                fail("ERR_VALIDATION", "Each goal_ratings entry needs a goal_id.")
            if not isinstance(entry["goal_id"], str):
                fail("ERR_VALIDATION", "goal_id must be a string.")
            rating = entry.get("rating")
            if rating is None:
                fail("ERR_VALIDATION", "Each goal_ratings entry needs a rating.")
            if not isinstance(rating, int) or isinstance(rating, bool):
                fail("ERR_VALIDATION", "rating must be an integer.")
            if rating < GOAL_MIN_RATING or rating > GOAL_MAX_RATING:
                fail("ERR_VALIDATION", "rating must be between %d and %d."
                     % (GOAL_MIN_RATING, GOAL_MAX_RATING))

    payload = validate_body([
        Field("narrative", "string", required=True),
        Field("goal_ratings", "array", required=True),
    ], cross=cross)
    session = session_or_404(session_id)

    goals = []
    for entry in payload["goal_ratings"]:                                 # rung 13
        goals.append(resource_or_404("goals", entry["goal_id"]))
    # Adjudication of friction 4 (§3.7): drafting a note against a session that
    # has NOT yet been completed is PERMITTED; only finalization requires
    # COMPLETED.  Refusing at draft time would make the finalize-time state
    # precondition unreachable (COMPLETED is terminal, so a note drafted only
    # against a completed session can never meet a non-completed parent), so
    # this reading keeps strictly more declared behaviour reachable.
    for goal in goals:                                                    # rung 19
        if goal["rider_id"] != session["rider_id"]:
            fail("ERR_INVALID_STATE",
                 "A rated goal must belong to this session's rider.")
        if goal["status"] == "DISCONTINUED":
            fail("ERR_INVALID_STATE", "A DISCONTINUED goal cannot be rated.")

    row = new_row("progress_notes")
    row.update({
        "session_id": session["id"],
        "rider_id": session["rider_id"],
        "author_instructor_id": caller_id(),
        "narrative": payload["narrative"],
        "goal_ratings": [{"goal_id": e["goal_id"], "rating": e["rating"]}
                         for e in payload["goal_ratings"]],
        "status": "DRAFT",
        "finalized_at": None,
        "recorded_service_hours": 0,
    })
    return object_response(serialize.progress_note(row), 201)


@bp.get("/progress-notes")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def list_notes():
    limit, offset = pagination()
    status = query_enum("status", NOTE_STATUSES)
    session_id = request.args.get("session_id")
    rider_id = request.args.get("rider_id")
    author_id = request.args.get("author_instructor_id")
    rows = all_rows("progress_notes")
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    if author_id is not None:
        rows = [r for r in rows if r["author_instructor_id"] == author_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.progress_note(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/progress-notes/<note_id>")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def read_note(note_id):
    return object_response(serialize.progress_note(
        resource_or_404("progress_notes", note_id)))


@bp.post("/progress-notes/<note_id>/finalize")
@endpoint(["Instructor"])
def finalize_note(note_id):
    existing = db["progress_notes"].get(note_id)
    if existing is not None and caller_role() == "Instructor" \
            and caller_id() != existing["author_instructor_id"]:            # rung 4
        fail("ERR_UNAUTHORIZED", "Only the note's own author may finalize it.")
    row = resource_or_404("progress_notes", note_id)                        # rung 12
    session = db["sessions"].get(row["session_id"])
    if row["status"] != "DRAFT":                                            # rung 19
        fail("ERR_INVALID_STATE", "Only a DRAFT note may be finalized.")
    if session is None or session["schedule_status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "The parent session is not COMPLETED.")

    stamp = clock.stamp()
    row["finalized_at"] = stamp
    row["recorded_service_hours"] = derive.session_service_hours(session)

    # Ratings are applied in the order the client supplied them - the array
    # order is the pinned processing order and is observable when two entries
    # name the same goal.
    for entry in row["goal_ratings"]:
        goal = db["goals"].get(entry["goal_id"])
        if goal is None:
            continue
        goal["current_rating"] = entry["rating"]
        goal["last_rated_at"] = stamp
        if entry["rating"] >= goal["target_rating"]:
            goal["consecutive_target_hits"] += 1
        else:
            goal["consecutive_target_hits"] = 0
        if goal["status"] == "STALE":
            goal["status"] = "ACTIVE"
        if goal["consecutive_target_hits"] >= GOAL_MET_CONSECUTIVE_HITS:
            goal["status"] = "MET"
        touch(goal)

    session_date = T.day_of(session["scheduled_start"].dt)
    report = gates.finalized_report_covering(session_date)
    if report is None:
        row["status"] = "FINALIZED"
    else:
        row["status"] = "AMENDED"
        report["amendment_count"] += 1
        touch(report)
    touch(row)
    return object_response(serialize.progress_note(row))
