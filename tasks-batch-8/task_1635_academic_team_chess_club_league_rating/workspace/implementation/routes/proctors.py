from datetime import timedelta

from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso, parse_date
from errors import (invalid_request, state_error, conflict_error,
                    forbidden_ownership)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404, touch
from services.serializers import assignment_json
from validate import Body, get_body

bp = Blueprint("proctors", __name__)

READ = ALL_ROLES


def _event_interval(event_type, meet_id, tournament_id):
    """(start_date, end_date) of the event: meets occupy their single
    scheduled_date; tournaments span [start_date, end_date]."""
    if event_type == "MEET":
        d = parse_date(store.meets[meet_id]["scheduled_date"])
        return d, d
    t = store.tournaments[tournament_id]
    return parse_date(t["start_date"]), parse_date(t["end_date"])


@bp.route("/api/proctor-assignments", methods=["POST"])
@require_roles("FederationAdmin")
def create_assignment():
    data = get_body()
    coach_id = data.get("coach_id")
    if isinstance(coach_id, str):
        get_or_404(store.coaches, coach_id, "coach")
    body = Body(data, {"coach_id", "event_type", "meet_id", "tournament_id"})
    cid = body.req_str("coach_id")
    coach = get_or_404(store.coaches, cid, "coach")
    event_type = body.req_enum("event_type", ("MEET", "TOURNAMENT"))
    meet_id = body.d.get("meet_id")
    tournament_id = body.d.get("tournament_id")
    if event_type == "MEET":
        if not isinstance(meet_id, str):
            raise invalid_request("meet_id is required when event_type is MEET")
        if tournament_id is not None:
            raise invalid_request("tournament_id must be absent for a MEET assignment")
        get_or_404(store.meets, meet_id, "meet")
    else:
        if not isinstance(tournament_id, str):
            raise invalid_request(
                "tournament_id is required when event_type is TOURNAMENT")
        if meet_id is not None:
            raise invalid_request("meet_id must be absent for a TOURNAMENT assignment")
        get_or_404(store.tournaments, tournament_id, "tournament")
    # buffered-overlap check (rung 12): existing ASSIGNED|CONFIRMED assignments
    # of this coach, each event interval expanded by one rest-day per side,
    # intersecting the new event's interval -> conflict.
    new_start, new_end = _event_interval(event_type, meet_id, tournament_id)
    one_day = timedelta(days=1)
    for a in store.proctor_assignments.values():
        if a["coach_id"] != cid or a["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        ex_start, ex_end = _event_interval(a["event_type"], a.get("meet_id"),
                                           a.get("tournament_id"))
        if (ex_start - one_day) <= new_end and new_start <= (ex_end + one_day):
            raise conflict_error("ERR_PROCTOR_DOUBLE_BOOKED",
                                 "Coach has an overlapping assignment within the "
                                 "rest-day buffer")
    now = now_iso()
    a = {"id": new_id(), "_seq": next_seq(), "created_at": now,
         "updated_at": now, "version": 1, "coach_id": cid,
         "event_type": event_type, "meet_id": meet_id,
         "tournament_id": tournament_id, "status": "ASSIGNED"}
    store.proctor_assignments[a["id"]] = a
    return success_object(assignment_json(a), 201)


@bp.route("/api/proctor-assignments", methods=["GET"])
@require_roles(*READ)
def list_assignments():
    items = list(store.proctor_assignments.values())
    for param, field in (("coach_id", "coach_id"), ("meet_id", "meet_id"),
                         ("tournament_id", "tournament_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(field) == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([assignment_json(a) for a in page], 200,
                         paginated=True, limit=limit, offset=offset,
                         total_count=total)


@bp.route("/api/proctor-assignments/<assignmentId>", methods=["GET"])
@require_roles(*READ)
def get_assignment(assignmentId):
    a = get_or_404(store.proctor_assignments, assignmentId, "proctor assignment")
    return success_object(assignment_json(a), 200)


@bp.route("/api/proctor-assignments/<assignmentId>/confirm", methods=["POST"])
@require_roles("Proctor")
def confirm_assignment(assignmentId):
    get_body()
    a = get_or_404(store.proctor_assignments, assignmentId, "proctor assignment")
    # state checked first (pinned)
    if a["status"] != "ASSIGNED":
        raise state_error("ERR_ASSIGNMENT_INVALID_STATE",
                          "Assignment is not ASSIGNED")
    if a["coach_id"] != g.user_id:
        raise forbidden_ownership()
    a["status"] = "CONFIRMED"
    touch(a)
    return success_object(assignment_json(a), 200)


@bp.route("/api/proctor-assignments/<assignmentId>/release", methods=["POST"])
@require_roles("FederationAdmin")
def release_assignment(assignmentId):
    get_body()
    a = get_or_404(store.proctor_assignments, assignmentId, "proctor assignment")
    if a["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise state_error("ERR_ASSIGNMENT_INVALID_STATE",
                          "Assignment is not ASSIGNED or CONFIRMED")
    a["status"] = "RELEASED"
    touch(a)
    return success_object(assignment_json(a), 200)


@bp.route("/api/proctor-assignments/<assignmentId>/mark-no-show", methods=["POST"])
@require_roles("FederationAdmin")
def mark_no_show(assignmentId):
    get_body()
    a = get_or_404(store.proctor_assignments, assignmentId, "proctor assignment")
    if a["status"] != "CONFIRMED":
        raise state_error("ERR_ASSIGNMENT_INVALID_STATE",
                          "Assignment is not CONFIRMED")
    a["status"] = "NO_SHOW"
    touch(a)
    return success_object(assignment_json(a), 200)
