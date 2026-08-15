"""Interview Evaluation routes."""

from flask import Blueprint, request, g

from db import db
from errors import (
    err_validation,
    err_forbidden,
    err_season_posture_forbidden,
    err_day_state_forbidden,
    err_slot_state_forbidden,
)
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_season,
    get_interview_day,
    get_interview_slot,
    get_evaluation,
    get_application,
    evaluation_view,
    auto_flip_application,
)
from utils import (
    parse_pagination,
    require_int,
    require_enum,
    stamp_new,
    touch,
)

bp = Blueprint("evaluations", __name__)

RECOMMENDATIONS = {"STRONG_HIRE", "HIRE", "LEAN_NO", "NO_HIRE"}


@bp.route("/interview-slots/<sid>/evaluations", methods=["POST"])
@require_auth(["Evaluator"])
def submit_evaluation(sid):
    slot = get_interview_slot(sid)
    day = get_interview_day(slot["interview_day_id"])
    season = get_season(day["season_id"])
    payload = request.get_json(silent=True) or {}
    score = require_int(payload, "score", min_value=1)
    if score > 5:
        raise err_validation("score must be 1..5")
    recommendation = require_enum(payload, "recommendation", RECOMMENDATIONS)

    # Ownership: X-User-ID must equal slot.evaluator_id
    if g.user_id != slot["evaluator_id"]:
        raise err_forbidden("Evaluator may submit only for own slots")
    # Posture
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    # Day state: evaluation submit requires OPEN or LOCKED
    if day["status"] not in ("OPEN", "LOCKED"):
        raise err_day_state_forbidden("evaluation submit requires day OPEN or LOCKED")
    # Slot state
    if slot["status"] != "BOOKED":
        raise err_slot_state_forbidden()
    # At most one evaluation per slot (uniqueness; implicit since slot must be BOOKED)

    e = {
        "interview_slot_id": sid,
        "evaluator_id": slot["evaluator_id"],
        "score": score,
        "recommendation": recommendation,
    }
    stamp_new(e)
    db.evaluations[e["id"]] = e
    # Slot completes
    slot["status"] = "COMPLETED"
    touch(slot)
    application = get_application(slot["application_id"])
    auto_flip_application(application)
    return success_object(evaluation_view(e), 201)


@bp.route("/evaluations/<eid>", methods=["PUT"])
@require_auth(["Evaluator"])
def revise_evaluation(eid):
    e = get_evaluation(eid)
    slot = get_interview_slot(e["interview_slot_id"])
    day = get_interview_day(slot["interview_day_id"])
    season = get_season(day["season_id"])
    payload = request.get_json(silent=True) or {}
    # Ownership
    if g.user_id != e["evaluator_id"]:
        raise err_forbidden("Evaluator may revise only own evaluations")
    # Posture
    if season["status"] != "SELECTION":
        raise err_season_posture_forbidden()
    # Day state: revise requires OPEN
    if day["status"] != "OPEN":
        raise err_day_state_forbidden("evaluation revise requires day OPEN")
    # Body shape
    if "score" in payload and payload["score"] is not None:
        v = payload["score"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1 or v > 5:
            raise err_validation("score must be an integer 1..5")
        e["score"] = v
    if "recommendation" in payload and payload["recommendation"] is not None:
        v = payload["recommendation"]
        if not isinstance(v, str) or v not in RECOMMENDATIONS:
            raise err_validation(f"recommendation must be one of {sorted(RECOMMENDATIONS)}")
        e["recommendation"] = v
    touch(e)
    return success_object(evaluation_view(e))


@bp.route("/evaluations/<eid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Evaluator"])
def get_one_evaluation(eid):
    e = get_evaluation(eid)
    if g.role == "Evaluator" and g.user_id != e["evaluator_id"]:
        raise err_forbidden("Evaluator may read only own evaluations")
    return success_object(evaluation_view(e))


@bp.route("/interview-slots/<sid>/evaluations", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Evaluator"])
def list_slot_evaluations(sid):
    slot = get_interview_slot(sid)
    if g.role == "Evaluator" and g.user_id != slot["evaluator_id"]:
        raise err_forbidden("Evaluator may read only own slot evaluations")
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.evaluations.values() if e["interview_slot_id"] == sid]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([evaluation_view(e) for e in page], total, limit, offset)
