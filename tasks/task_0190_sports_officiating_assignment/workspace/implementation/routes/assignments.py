"""Assignment endpoints (PRD §3.6, §3.7, §3.11, §3.13).

GET    /assignments                         filter by game_id/official_id/crew_slot_id
GET    /assignments/{id}
POST   /assignments/{id}/accept             OFFERED -> ACCEPTED (OCC)
POST   /assignments/{id}/decline            OFFERED -> DECLINED (penalty)
POST   /assignments/{id}/withdraw           ACCEPTED -> CANCELLED (late-decline penalty)
POST   /assignments/{id}/no-show            ACCEPTED -> NO_SHOW (no-show penalty)
POST   /assignments/{id}/evaluations        rate a COMPLETED assignment
GET    /assignments/{id}/evaluations
POST   /assignments/{id}/appeals            appeal a DECLINED/NO_SHOW penalty
GET    /assignments/{id}/appeals
"""
from flask import Blueprint, request

import db
import lookup
import serialize
from errors import (
    err, ERR_INVALID_STATE, ERR_NOT_ASSIGNMENT_OWNER, ERR_GAME_NOT_OPEN,
    ERR_GAME_LOCKED, ERR_GAME_NOT_STARTED, ERR_STALE_GAME_VERSION,
    ERR_INVALID_REQUEST, ERR_ASSIGNMENT_NOT_COMPLETED, ERR_NOT_APPEALABLE,
)
from middleware import get_user_context, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response
from services import validate, derive, transitions, eligibility
from services.transitions import bubble_game_after_fill_change
from clock import now
from services.intervals import game_interval

bp = Blueprint("assignments", __name__)

READ_ROLES = {"LeagueAdmin", "Assignor", "Official", "Evaluator"}


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    game_id = request.args.get("game_id")
    official_id = request.args.get("official_id")
    crew_slot_id = request.args.get("crew_slot_id")
    with db.lock:
        rows = list(db.assignments.values())
        if game_id is not None:
            rows = [a for a in rows if a["game_id"] == game_id]
        if official_id is not None:
            rows = [a for a in rows if a["official_id"] == official_id]
        if crew_slot_id is not None:
            rows = [a for a in rows if a["crew_slot_id"] == crew_slot_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.assignment(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.assignment(assignment_id)
        return object_response(serialize.assignment(rec))


def _require_owner(user_id, assignment):
    if assignment["official_id"] != user_id:
        err(ERR_NOT_ASSIGNMENT_OWNER, "acting official does not own this assignment")


@bp.route("/assignments/<assignment_id>/accept", methods=["POST"])
def accept_assignment(assignment_id):
    user_id, role = get_user_context()
    require_role(role, {"Official"})
    data = validate.body()
    with db.lock:
        a = lookup.assignment(assignment_id)
        if a["status"] != "OFFERED":
            err(ERR_INVALID_STATE, "assignment not in OFFERED")
        _require_owner(user_id, a)
        game = db.games.get(a["game_id"])
        if game["status"] != "OPEN":
            err(ERR_GAME_NOT_OPEN, "game is not OPEN")
        official = db.officials.get(a["official_id"])
        # No already-ACCEPTED assignment overlaps this game's interval.
        eligibility.check_double_booking(official, game, statuses=("ACCEPTED",))
        # OCC on game version.
        _check_game_version(game, data)
        a["status"] = "ACCEPTED"
        db.touch(a)
        slot = db.crew_slots.get(a["crew_slot_id"])
        transitions.fill_slot(slot)
        bubble_game_after_fill_change(game)
        db.touch(game)  # offer/accept increments game version (PRD §3.6)
        return object_response(serialize.assignment(a))


def _check_game_version(game, data):
    if "expected_game_version" not in data or data["expected_game_version"] is None:
        err(ERR_INVALID_REQUEST, "expected_game_version is required")
    expected = data["expected_game_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err(ERR_INVALID_REQUEST, "expected_game_version must be an integer")
    if expected != game["version"]:
        err(ERR_STALE_GAME_VERSION, "game version mismatch")


@bp.route("/assignments/<assignment_id>/decline", methods=["POST"])
def decline_assignment(assignment_id):
    user_id, role = get_user_context()
    require_role(role, {"Official"})
    with db.lock:
        a = lookup.assignment(assignment_id)
        if a["status"] != "OFFERED":
            err(ERR_INVALID_STATE, "assignment not in OFFERED")
        _require_owner(user_id, a)
        game = db.games.get(a["game_id"])
        official = db.officials.get(a["official_id"])
        a["status"] = "DECLINED"
        db.touch(a)
        transitions.assess_decline_penalty(a, official, game)
        slot = db.crew_slots.get(a["crew_slot_id"])
        transitions.vacate_slot(slot)
        # Slot was OFFERED (not FILLED), so crew_filled_count is unaffected,
        # but recompute defensively for game counter consistency.
        bubble_game_after_fill_change(game)
        derive.recompute_official_derived(official)
        return object_response(serialize.assignment(a))


@bp.route("/assignments/<assignment_id>/withdraw", methods=["POST"])
def withdraw_assignment(assignment_id):
    user_id, role = get_user_context()
    require_role(role, {"Official"})
    with db.lock:
        a = lookup.assignment(assignment_id)
        if a["status"] != "ACCEPTED":
            err(ERR_INVALID_STATE, "assignment not in ACCEPTED")
        _require_owner(user_id, a)
        game = db.games.get(a["game_id"])
        if game["status"] not in {"OPEN", "STAFFED"}:
            err(ERR_GAME_LOCKED, "game is locked; cannot withdraw")
        official = db.officials.get(a["official_id"])
        a["status"] = "CANCELLED"
        db.touch(a)
        transitions.assess_decline_penalty(a, official, game)
        slot = db.crew_slots.get(a["crew_slot_id"])
        transitions.vacate_slot(slot)
        bubble_game_after_fill_change(game)
        derive.recompute_official_derived(official)
        return object_response(serialize.assignment(a))


@bp.route("/assignments/<assignment_id>/no-show", methods=["POST"])
def no_show_assignment(assignment_id):
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    with db.lock:
        a = lookup.assignment(assignment_id)
        if a["status"] != "ACCEPTED":
            err(ERR_INVALID_STATE, "assignment not in ACCEPTED")
        game = db.games.get(a["game_id"])
        if game["status"] not in {"STAFFED", "LOCKED"}:
            err(ERR_INVALID_STATE, "game not in STAFFED or LOCKED")
        g_start, _ = game_interval(game)
        if not (g_start <= now()):
            err(ERR_GAME_NOT_STARTED, "game has not started yet")
        official = db.officials.get(a["official_id"])
        a["status"] = "NO_SHOW"
        db.touch(a)
        transitions.assess_no_show_penalty(a, official, game)
        slot = db.crew_slots.get(a["crew_slot_id"])
        transitions.vacate_slot(slot)
        # STAFFED may bubble back to OPEN; LOCKED stays LOCKED with a vacant slot.
        bubble_game_after_fill_change(game)
        derive.recompute_official_derived(official)
        return object_response(serialize.assignment(a))


# ---- Evaluations ---------------------------------------------------------

@bp.route("/assignments/<assignment_id>/evaluations", methods=["POST"])
def create_evaluation(assignment_id):
    _, role = get_user_context()
    require_role(role, {"Evaluator"})
    data = validate.body()
    with db.lock:
        a = lookup.assignment(assignment_id)
        # Business constraint (priority 13): COMPLETED + at most one eval.
        if a["status"] != "COMPLETED":
            err(ERR_ASSIGNMENT_NOT_COMPLETED, "assignment is not COMPLETED")
        existing = any(e["assignment_id"] == assignment_id
                       for e in db.evaluations.values())
        if existing:
            err(ERR_ASSIGNMENT_NOT_COMPLETED, "assignment already evaluated")
        score = validate.number(data, "score", minimum=1.0, maximum=5.0)
        comment = validate.opt_str(data, "comment")
        rec = {
            "assignment_id": assignment_id,
            "official_id": a["official_id"],
            "score": score,
            "comment": comment,
        }
        db.stamp_create(rec, common_fields=False)
        db.evaluations[rec["id"]] = rec
        official = db.officials.get(a["official_id"])
        if official is not None:
            derive.recompute_official_derived(official)
    return object_response(serialize.evaluation(rec), 201)


@bp.route("/assignments/<assignment_id>/evaluations", methods=["GET"])
def list_evaluations(assignment_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        lookup.assignment(assignment_id)
        rows = [e for e in db.evaluations.values()
                if e["assignment_id"] == assignment_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.evaluation(r) for r in page]
    return array_response(items, limit, offset, total)


# ---- Penalty appeals -----------------------------------------------------

@bp.route("/assignments/<assignment_id>/appeals", methods=["POST"])
def create_appeal(assignment_id):
    user_id, role = get_user_context()
    require_role(role, {"Official"})
    data = validate.body()
    with db.lock:
        a = lookup.assignment(assignment_id)
        _require_owner(user_id, a)
        # Appealable: DECLINED/NO_SHOW with penalty_assessed_points > 0 and no
        # existing PENDING/UPHELD appeal (priority 14).
        if a["status"] not in {"DECLINED", "NO_SHOW"} or a.get("penalty_assessed_points", 0) <= 0:
            err(ERR_NOT_APPEALABLE, "assignment is not appealable")
        for ap in db.penalty_appeals.values():
            if ap["assignment_id"] == assignment_id and ap["status"] in {"PENDING", "UPHELD"}:
                err(ERR_NOT_APPEALABLE, "an active appeal already exists")
        reason = validate.require_str(data, "reason")
        rec = {
            "assignment_id": assignment_id,
            "official_id": a["official_id"],
            "reason": reason,
            "status": "PENDING",
            "reversed_points": 0,
        }
        db.stamp_create(rec)
        db.penalty_appeals[rec["id"]] = rec
    return object_response(serialize.appeal(rec), 201)


@bp.route("/assignments/<assignment_id>/appeals", methods=["GET"])
def list_appeals(assignment_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        lookup.assignment(assignment_id)
        rows = [ap for ap in db.penalty_appeals.values()
                if ap["assignment_id"] == assignment_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.appeal(r) for r in page]
    return array_response(items, limit, offset, total)
