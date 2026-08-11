"""Goals, ratings and mastery."""

from flask import Blueprint

import calc
import enums
import lookups as L
import serial
from ctx import Body, Refs, endpoint, pagination, paginate, resolve_one
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, sort_rows, touch

bp = Blueprint("goals", __name__)


def _scope_goal_param(context):
    goal = db.get("goals", context.params.get("goal_id"))
    return [goal["participant_id"]] if goal else []


def _scope_goal_filter(context):
    row = db.get("participants", context.q("participant_id"))
    return [row["id"]] if row else []


def _scope_rating_filter(context):
    goal = db.get("goals", context.q("goal_id"))
    return [goal["participant_id"]] if goal else []


def _rating_session(context):
    session_id = context.body.get("session_id")
    return db.get("program_sessions", session_id) if isinstance(session_id, str) else None


# ---------------------------------------------------------------------------
# goals
# ---------------------------------------------------------------------------

@bp.route("/recreation/goals", methods=["POST"])
@endpoint(roles=("IntakeCoordinator",))
def create_goal(context):
    participant_id = context.body.get("participant_id")
    if isinstance(participant_id, str):
        resolve_one("participant", participant_id)
    body = Body(context.body)
    fields = {
        "participant_id": body.req_string("participant_id"),
        "title": body.req_string("title"),
        "measure": body.req_string("measure"),
        "baseline_value": body.req_int("baseline_value", minimum=1, maximum=5),
        "target_value": body.req_int("target_value", minimum=1, maximum=5),
        "mastery_mode": body.req_enum("mastery_mode", enums.MASTERY_MODES),
        "mastery_criterion_score": body.req_int("mastery_criterion_score", minimum=1, maximum=5),
        "mastery_window_m": body.opt_int("mastery_window_m", 5, minimum=1),
        "mastery_hits_n": body.opt_int("mastery_hits_n", 4, minimum=1),
        "review_due_on": body.req_date("review_due_on"),
        "rating_count": 0,
        "status": "ACTIVE",
    }
    body.check_enums()
    if fields["mastery_hits_n"] > fields["mastery_window_m"]:
        raise ApiError("ERR_VALIDATION", "mastery_hits_n must not exceed mastery_window_m.")
    resolve_one("participant", fields["participant_id"])
    return ok(serial.dump(insert("goals", fields)), 201)


@bp.route("/recreation/goals", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_goal_filter)
def list_goals(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("goals"))
    participant_id = context.q("participant_id")
    status = context.q("status")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/goals/<goal_id>", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_goal_param)
def read_goal(context, goal_id):
    return ok(serial.dump(resolve_one("goal", goal_id)))


@bp.route("/recreation/goals/<goal_id>/ratings", methods=["POST"])
@endpoint(roles=("ActivityLead",), delivery=_rating_session)
def create_rating(context, goal_id):
    refs = Refs()
    session_id = context.body.get("session_id")
    if isinstance(session_id, str):
        refs.add("session", session_id, path=False)
    refs.add("goal", goal_id)
    refs.resolve()

    body = Body(context.body)
    body.req_string("session_id")
    score = body.req_int("score", minimum=1, maximum=5)
    note = body.opt_string("note", "")
    body.check_enums()

    session = resolve_one("session", session_id)
    goal = resolve_one("goal", goal_id)
    participant = L.participant_of_goal(goal)

    enrollment = None
    for row in L.enrollments_of_participant(participant):
        if row["session_id"] == session["id"]:
            enrollment = row
            break
    if enrollment is None:                                            # rung 30
        raise ApiError("ERR_PROGRAM_SESSION_MISMATCH")

    for rating in L.ratings_of_goal(goal):                            # rung 32
        if rating["session_id"] == session["id"]:
            raise ApiError("ERR_DUPLICATE_GOAL_RATING")

    if enrollment["enrollment_status"] != "ATTENDED":                 # rung 44
        raise ApiError("ERR_RATING_SESSION_NOT_ATTENDED")

    row = insert(
        "goal_ratings",
        {
            "goal_id": goal["id"],
            "session_id": session["id"],
            "rated_by_staff_id": context.user_id,
            "score": score,
            "rated_session_start_at": session["start_at"],
            "note": note,
        },
    )
    goal["rating_count"] += 1
    mastered = calc.goal_mastery_status(goal)
    if goal["status"] == "ACTIVE" and mastered:
        goal["status"] = "MASTERED"
    elif goal["status"] == "MASTERED" and not mastered:
        goal["status"] = "ACTIVE"
    touch(goal)
    return ok(serial.dump(row), 201)


# ---------------------------------------------------------------------------
# goal ratings
# ---------------------------------------------------------------------------

@bp.route("/recreation/goal-ratings", methods=["GET"])
@endpoint(roles=enums.ALL_ROLES, scope=_scope_rating_filter)
def list_ratings(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("goal_ratings"))
    goal_id = context.q("goal_id")
    session_id = context.q("session_id")
    rated_by = context.q("rated_by_staff_id")
    if goal_id is not None:
        rows = [r for r in rows if r["goal_id"] == goal_id]
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if rated_by is not None:
        rows = [r for r in rows if r["rated_by_staff_id"] == rated_by]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/goal-ratings/<rating_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_rating(context, rating_id):
    return ok(serial.dump(resolve_one("rating", rating_id)))
