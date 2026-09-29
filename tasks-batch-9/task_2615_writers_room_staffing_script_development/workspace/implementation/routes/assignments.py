"""Script assignments: fees, guarantees, notes, approval and void (PRD 3.5, 3.6)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, LEGAL_COUNSEL, SHOWRUNNER,
                        STUDIO_EXECUTIVE, WRITER, fetch, require)
from response import created, ok
from routes.common import list_out, match, out
from services import calc, domain
from validation import body_json, filter_value, raw, v_enum, v_int, v_str

bp = Blueprint("assignments", __name__)

READ_ROLES = (STUDIO_EXECUTIVE, SHOWRUNNER, GUILD_ADMINISTRATOR, LEGAL_COUNSEL, WRITER)
LIVE_STATUSES = ("DRAFTING", "DELIVERED", "IN_NOTES", "APPROVED")
NON_TERMINAL = ("DRAFTING", "DELIVERED", "IN_NOTES", "REASSIGNMENT_PENDING")


def _select_seat(writer_id, season_id):
    """PRD 3.5 selector: CONFIRMED seats in ACTIVE rooms, confirmed_at ASC."""
    candidates = []
    for seat in domain.seats_of_writer(writer_id):
        if seat["status"] != "CONFIRMED":
            continue
        room = db.rooms.get(seat["room_id"])
        if room is None or room["season_id"] != season_id or room["status"] != "ACTIVE":
            continue
        candidates.append(seat)
    candidates.sort(key=lambda s: (s["confirmed_at"], s["created_at"], s["_seq"]))
    return candidates[0] if candidates else None


@bp.post("/episodes/<episode_id>/script-assignments")
def create_assignment(episode_id):
    actor = require(SHOWRUNNER)
    episode = fetch(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
    season = domain.season_of_episode(episode)
    agreement = domain.agreement_of(season)
    body = body_json()
    writer_ref = raw(body, "writer_id")
    writer = None
    if writer_ref is not None:
        writer = fetch(db.writers, writer_ref, "ERR_WRITER_NOT_FOUND")
    predecessor_ref = raw(body, "predecessor_assignment_id")
    predecessor = None
    if predecessor_ref is not None:
        predecessor = fetch(db.assignments, predecessor_ref, "ERR_ASSIGNMENT_NOT_FOUND")
    row = base_row()
    row["assignment_type"] = v_enum(body, "assignment_type", calc.ASSIGNMENT_TYPES)
    expected = v_int(body, "expected_episode_version")
    if writer is None:
        raise ApiError("ERR_INVALID_REQUEST")
    # 12. season-showrunner authority, 13. OCC, 14. episode state
    if season["showrunner_writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_SEASON_SHOWRUNNER")
    if expected != episode["version"]:
        raise ApiError("ERR_STALE_EPISODE_VERSION")
    if episode["script_readiness"] == "LOCKED":
        raise ApiError("ERR_EPISODE_ALREADY_LOCKED")
    # 18. type exclusivity
    for other in domain.assignments_of(episode["id"]):
        if (other["assignment_type"] == row["assignment_type"]
                and other["status"] in LIVE_STATUSES):
            raise ApiError("ERR_ASSIGNMENT_TYPE_CONFLICT")
    # 19. staffing linkage
    seat = _select_seat(writer["id"], season["id"])
    if seat is None:
        raise ApiError("ERR_WRITER_NOT_STAFFED")
    # 19. predecessor linkage
    if row["assignment_type"] in ("REWRITE", "PRODUCTION_POLISH"):
        if (predecessor is None or predecessor["episode_id"] != episode["id"]
                or predecessor["status"] != "APPROVED"):
            raise ApiError("ERR_PREDECESSOR_NOT_APPROVED")
    elif predecessor_ref is not None:
        raise ApiError("ERR_PREDECESSOR_NOT_ALLOWED")
    row["episode_id"] = episode["id"]
    row["writer_id"] = writer["id"]
    row["room_seat_id"] = seat["id"]
    row["predecessor_assignment_id"] = predecessor["id"] if predecessor else None
    row["gross_fee_cents"] = calc.script_fee(agreement, episode, row["assignment_type"])
    row["status"] = "DRAFTING"
    row["approved_at"] = None
    row["approved_by_role"] = None
    row["revision_round"] = 0
    row["late_milestone_count"] = 0
    row["guarantee_slot_applied"] = False
    row["guarantee_offset_cents"] = 0
    row["payable_fee_cents"] = row["gross_fee_cents"]
    plan = domain.settle_plan(seat, season, agreement, extra=row)
    applied, offset, payable = plan.get(
        row["id"], (False, 0, row["gross_fee_cents"]))
    row["guarantee_slot_applied"] = applied
    row["guarantee_offset_cents"] = offset
    row["payable_fee_cents"] = payable
    # 20. fiscal ceiling: the script fee budget
    if season["script_fee_committed_cents"] + payable > season["script_fee_budget_cents"]:
        raise ApiError("ERR_SCRIPT_FEE_BUDGET_EXCEEDED")
    domain.set_assignment_due_dates(row, episode, agreement)
    db.assignments[row["id"]] = row
    domain.append_ledger(season["id"], row, "SCRIPT_FEE_ACCRUAL", row["gross_fee_cents"],
                         "%s script fee accrual" % row["assignment_type"])
    if applied:
        domain.append_ledger(season["id"], row, "GUARANTEE_OFFSET", -offset,
                             "episodic guarantee offset on %s" % row["assignment_type"])
    domain.recompute_season_committed_fees(season)
    domain.recount_seat_guarantees(seat)
    domain.synthesize_milestones(row, agreement)
    domain.recompute_late_milestone_count(row)
    readiness = episode["script_readiness"]
    if readiness == "NOT_STARTED":
        episode["script_readiness"] = "IN_PROGRESS"
    elif readiness == "READY" and row["assignment_type"] == "REWRITE":
        episode["script_readiness"] = "IN_PROGRESS"
    domain.recompute_coverage(season)
    touch(episode)
    return created(out(row))


@bp.post("/script-assignments/<assignment_id>/issue-notes")
def issue_notes(assignment_id):
    actor = require(SHOWRUNNER)
    assignment = fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    episode = domain.episode_of_assignment(assignment)
    season = domain.season_of_episode(episode)
    agreement = domain.agreement_of(season)
    body = body_json()
    v_str(body, "notes", 1, 4000)
    if season["showrunner_writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_SEASON_SHOWRUNNER")
    if assignment["status"] != "DELIVERED":
        raise ApiError("ERR_ASSIGNMENT_NOT_DELIVERED")
    if assignment["revision_round"] + 1 > agreement["max_free_revision_rounds"]:
        raise ApiError("ERR_REVISION_CAP_EXCEEDED")
    assignment["status"] = "IN_NOTES"
    assignment["revision_round"] += 1
    touch(assignment)
    for milestone in domain.milestones_of(assignment["id"]):
        if milestone["status"] == "DELIVERED":
            milestone["status"] = "NOTES_ISSUED"
            touch(milestone)
    if episode["script_readiness"] == "READY":
        episode["script_readiness"] = "IN_PROGRESS"
        touch(episode)
        domain.recompute_coverage(season)
    return ok(out(assignment))


@bp.post("/script-assignments/<assignment_id>/approve")
def approve(assignment_id):
    actor = require(SHOWRUNNER, STUDIO_EXECUTIVE)
    assignment = fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    episode = domain.episode_of_assignment(assignment)
    season = domain.season_of_episode(episode)
    agreement = domain.agreement_of(season)
    if actor.role == SHOWRUNNER and season["showrunner_writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_SEASON_SHOWRUNNER")
    if assignment["status"] != "DELIVERED":
        raise ApiError("ERR_ASSIGNMENT_NOT_DELIVERED")
    if actor.role == SHOWRUNNER and assignment["writer_id"] == actor.user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN")
    assignment["status"] = "APPROVED"
    assignment["approved_at"] = db.now()
    assignment["approved_by_role"] = (
        "SHOWRUNNER" if actor.role == SHOWRUNNER else "STUDIO_EXECUTIVE")
    touch(assignment)
    for milestone in domain.milestones_of(assignment["id"]):
        if milestone["status"] in ("DELIVERED", "NOTES_ISSUED"):
            milestone["status"] = "ACCEPTED"
            touch(milestone)
    if assignment["assignment_type"] in ("TELEPLAY", "STORY_AND_TELEPLAY"):
        episode["approved_teleplay_assignment_id"] = assignment["id"]
        if episode["script_readiness"] == "IN_PROGRESS":
            episode["script_readiness"] = "READY"
    if episode["credit_status"] == "PENDING":
        episode["credit_status"] = "SUBMISSIONS_OPEN"
    if season["guarantee_application_mode"] == "CHRONOLOGICAL_ON_ACCEPTANCE":
        seat = db.seats.get(assignment.get("room_seat_id"))
        if seat is not None:
            domain.resettle_seat(seat, season, agreement)
    domain.recompute_coverage(season)
    touch(episode)
    return ok(out(assignment))


@bp.post("/script-assignments/<assignment_id>/void")
def void(assignment_id):
    require(SHOWRUNNER, STUDIO_EXECUTIVE)
    assignment = fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    episode = domain.episode_of_assignment(assignment)
    season = domain.season_of_episode(episode)
    agreement = domain.agreement_of(season)
    body = body_json()
    v_str(body, "reason", 1, 500)
    if assignment["status"] not in NON_TERMINAL:
        raise ApiError("ERR_ASSIGNMENT_ALREADY_TERMINAL")
    if episode["script_readiness"] == "LOCKED":
        raise ApiError("ERR_EPISODE_ALREADY_LOCKED")
    had_slot = assignment["guarantee_slot_applied"]
    prior = sum(e["amount_cents"] for e in domain.ledger_of_assignment(assignment["id"]))
    assignment["status"] = "VOID"
    assignment["guarantee_slot_applied"] = False
    assignment["guarantee_offset_cents"] = 0
    assignment["payable_fee_cents"] = 0
    touch(assignment)
    domain.append_ledger(season["id"], assignment, "FEE_REVERSAL", -prior,
                         "void reversal of %s fee" % assignment["assignment_type"])
    domain.recompute_season_committed_fees(season)
    seat = db.seats.get(assignment.get("room_seat_id"))
    if seat is not None:
        domain.recount_seat_guarantees(seat)
        if (had_slot
                and season["guarantee_application_mode"] == "CHRONOLOGICAL_ON_ACCEPTANCE"):
            domain.resettle_seat(seat, season, agreement)
    rows = domain.assignments_of(episode["id"])
    if (episode["script_readiness"] == "IN_PROGRESS"
            and all(a["status"] == "VOID" for a in rows)):
        episode["script_readiness"] = "NOT_STARTED"
        touch(episode)
    domain.recompute_coverage(season)
    return ok(out(assignment))


@bp.get("/script-assignments/<assignment_id>")
def get_assignment(assignment_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")))


@bp.get("/script-assignments")
def list_assignments():
    require(*READ_ROLES)
    rows = list(db.assignments.values())
    rows = match(rows, "episode_id", filter_value("episode_id"))
    rows = match(rows, "writer_id", filter_value("writer_id"))
    rows = match(rows, "room_seat_id", filter_value("room_seat_id"))
    rows = match(rows, "predecessor_assignment_id",
                 filter_value("predecessor_assignment_id"))
    rows = match(rows, "status", filter_value("status"))
    return list_out(rows)
