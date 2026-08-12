"""InternEvaluation routes (MID/FINAL) + record-return-offer-outcome."""

from flask import Blueprint, request, g

from db import db
from errors import (
    err_validation,
    err_forbidden,
    err_season_posture_forbidden,
    err_assignment_state_forbidden,
    err_evaluation_already_submitted,
    err_mid_evaluation_required,
)
from middleware import require_auth
from response import success_object, success_list
from services.calculations import return_offer_decision
from services.domain import (
    get_project_assignment,
    get_intern_evaluation,
    intern_evaluation_view,
    project_assignment_view,
    assignment_season,
)
from utils import (
    parse_pagination,
    require_int,
    require_bool,
    require_enum,
    new_id,
    format_iso,
    now_utc,
    touch,
)

bp = Blueprint("intern_evaluations", __name__)

EVAL_TYPES = {"MID", "FINAL"}
OUTCOMES = {"ACCEPTED", "DECLINED"}


@bp.route("/project-assignments/<aid>/intern-evaluations", methods=["POST"])
@require_auth(["Mentor"])
def submit_intern_evaluation(aid):
    assignment = get_project_assignment(aid)
    season = assignment_season(assignment)
    payload = request.get_json(silent=True) or {}
    eval_type = require_enum(payload, "eval_type", EVAL_TYPES)
    rating = require_int(payload, "rating", min_value=1)
    if rating > 5:
        raise err_validation("rating must be 1..5")
    would_rehire = require_bool(payload, "would_rehire")
    # Ownership: X-User-ID must equal assignment.mentor_id
    if g.user_id != assignment["mentor_id"]:
        raise err_forbidden("Mentor may submit only for own assignments")
    # Posture
    if season["status"] != "INTERN_ACTIVE":
        raise err_season_posture_forbidden()
    # State: assignment must be ACTIVE
    if assignment["status"] != "ACTIVE":
        raise err_assignment_state_forbidden("intern-evaluation requires ACTIVE assignment")
    # Uniqueness per (assignment, eval_type)
    for ev in db.intern_evaluations.values():
        if ev["project_assignment_id"] == aid and ev["eval_type"] == eval_type:
            raise err_evaluation_already_submitted()
    # FINAL requires existing MID
    if eval_type == "FINAL":
        has_mid = any(
            ev["project_assignment_id"] == aid and ev["eval_type"] == "MID"
            for ev in db.intern_evaluations.values()
        )
        if not has_mid:
            raise err_mid_evaluation_required()

    e = {
        "id": new_id(),
        "project_assignment_id": aid,
        "eval_type": eval_type,
        "rating": rating,
        "would_rehire": would_rehire,
        "submitted_by_mentor_id": g.user_id,
        "created_at": format_iso(now_utc()),
    }
    db.intern_evaluations[e["id"]] = e

    # FINAL computes return-offer decision
    if eval_type == "FINAL":
        mid_eval = next(
            (ev for ev in db.intern_evaluations.values()
             if ev["project_assignment_id"] == aid and ev["eval_type"] == "MID"),
            None,
        )
        decision = return_offer_decision(mid_eval["rating"], rating, would_rehire)
        assignment["return_offer_decision"] = decision
        touch(assignment)
        if decision == "EXTENDED":
            season["return_offers_extended_count"] += 1
            touch(season)
    return success_object(intern_evaluation_view(e), 201)


@bp.route("/project-assignments/<aid>/intern-evaluations", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Mentor"])
def list_intern_evaluations(aid):
    assignment = get_project_assignment(aid)
    if g.role == "Mentor" and g.user_id != assignment["mentor_id"]:
        raise err_forbidden("Mentor may read only own intern evaluations")
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.intern_evaluations.values() if e["project_assignment_id"] == aid]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([intern_evaluation_view(e) for e in page], total, limit, offset)


@bp.route("/intern-evaluations/<eid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Mentor"])
def get_one_intern_evaluation(eid):
    e = get_intern_evaluation(eid)
    if g.role == "Mentor":
        assignment = get_project_assignment(e["project_assignment_id"])
        if g.user_id != assignment["mentor_id"]:
            raise err_forbidden("Mentor may read only own intern evaluations")
    return success_object(intern_evaluation_view(e))


@bp.route("/project-assignments/<aid>/record-return-offer-outcome", methods=["POST"])
@require_auth(["Recruiter"])
def record_return_offer_outcome(aid):
    assignment = get_project_assignment(aid)
    season = assignment_season(assignment)
    payload = request.get_json(silent=True) or {}
    outcome = require_enum(payload, "outcome", OUTCOMES)
    # Posture
    if season["status"] != "INTERN_ACTIVE":
        raise err_season_posture_forbidden()
    # State
    if assignment["status"] not in ("ACTIVE", "COMPLETED"):
        raise err_assignment_state_forbidden("record-return-offer-outcome requires ACTIVE or COMPLETED")
    if assignment["return_offer_decision"] != "EXTENDED" or assignment["return_offer_outcome"] != "NONE":
        raise err_assignment_state_forbidden("return_offer_decision must be EXTENDED and outcome NONE")
    assignment["return_offer_outcome"] = outcome
    touch(assignment)
    if outcome == "ACCEPTED":
        season["return_offers_accepted_count"] += 1
        touch(season)
    return success_object(project_assignment_view(assignment))
