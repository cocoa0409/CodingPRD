"""ReEvaluation endpoints."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_INVALID_PLACEMENT_STATE,
    ERR_INVALID_REQUEST,
    ERR_REEVAL_ALREADY_OPEN,
    ERR_REEVAL_NOT_IN_REVIEW,
    ERR_REEVAL_OUTCOME_MISMATCH,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    get_json_body,
    require_fields,
    require_enum,
    get_or_404,
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_created,
    parse_date,
    one_decimal_ok,
    serialize_reeval,
)
from services import domain

bp = Blueprint("reevaluations", __name__)


@bp.route("/gifted/placements/<pid>/re-evaluations", methods=["POST"])
def create_reevaluation(pid):
    require_roles("GiftedCoordinator")
    placement = get_or_404(db.service_placements, pid, "placement")
    body = get_json_body()
    require_fields(body, ["due_on"])
    due_raw = body["due_on"]
    parse_date(due_raw, "due_on")

    # placement state gate (priority 7)
    if placement["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_PLACEMENT_STATE, "re-evaluation requires placement status ACTIVE", 409)

    # at most one non-CONCLUDED per placement (priority 10)
    for r in db.re_evaluations.values():
        if r["placement_id"] == pid and r["status"] != "CONCLUDED":
            raise ApiError(ERR_REEVAL_ALREADY_OPEN, "a non-CONCLUDED re-evaluation already exists for the placement", 409)

    ts = now_iso()
    reeval = {
        "id": new_id(),
        "placement_id": pid,
        "due_on": due_raw,
        "status": "SCHEDULED",
        "growth_percentile": None,
        "service_rating": None,
        "teacher_rating": None,
        "exit_score": None,
        "outcome": None,
        "concluded_on": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.re_evaluations[reeval["id"]] = reeval
    return success_object(serialize_reeval(reeval), 201)


@bp.route("/gifted/placements/<pid>/re-evaluations", methods=["GET"])
def list_reevaluations(pid):
    require_roles(*ALL_ROLES)
    get_or_404(db.service_placements, pid, "placement")
    items = [r for r in db.re_evaluations.values() if r["placement_id"] == pid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_reeval(r) for r in page], total, limit, offset)


@bp.route("/gifted/re-evaluations/<rid>/conclude", methods=["POST"])
def conclude_reevaluation(rid):
    require_roles("GiftedCoordinator")
    reeval = get_or_404(db.re_evaluations, rid, "re-evaluation")
    body = get_json_body()
    require_fields(body, ["growth_percentile", "service_rating", "teacher_rating", "outcome"])

    growth = body["growth_percentile"]
    if isinstance(growth, bool) or not isinstance(growth, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "growth_percentile must be a number", 400)
    if growth < 0.0 or growth > 100.0:
        raise ApiError(ERR_INVALID_REQUEST, "growth_percentile must be between 0.0 and 100.0 inclusive", 400)
    if not one_decimal_ok(growth):
        raise ApiError(ERR_INVALID_REQUEST, "growth_percentile must have at most one decimal place", 400)

    service_rating = body["service_rating"]
    if isinstance(service_rating, bool) or not isinstance(service_rating, int) or service_rating < 1 or service_rating > 4:
        raise ApiError(ERR_INVALID_REQUEST, "service_rating must be an integer between 1 and 4 inclusive", 400)

    teacher_rating = body["teacher_rating"]
    if isinstance(teacher_rating, bool) or not isinstance(teacher_rating, int) or teacher_rating < 1 or teacher_rating > 5:
        raise ApiError(ERR_INVALID_REQUEST, "teacher_rating must be an integer between 1 and 5 inclusive", 400)

    outcome = require_enum(body, "outcome", {"RETAINED", "PROBATION", "EXITED"})

    # state gate (priority 7)
    if reeval["status"] != "IN_REVIEW":
        raise ApiError(ERR_REEVAL_NOT_IN_REVIEW, "conclude requires re-evaluation status IN_REVIEW", 409)

    placement = db.service_placements.get(reeval["placement_id"])
    is_on_probation = bool(placement and placement.get("is_on_probation"))

    exit_score = domain.compute_exit_score(growth, service_rating, teacher_rating)
    effective = domain.effective_outcome(exit_score, is_on_probation)

    if outcome != effective:
        raise ApiError(
            ERR_REEVAL_OUTCOME_MISMATCH,
            "submitted outcome differs from the computed effective outcome",
            422,
        )

    reeval["growth_percentile"] = growth
    reeval["service_rating"] = service_rating
    reeval["teacher_rating"] = teacher_rating
    reeval["exit_score"] = exit_score
    reeval["outcome"] = outcome
    reeval["concluded_on"] = db.today().isoformat()
    reeval["status"] = "CONCLUDED"
    domain.touch(reeval)

    if placement is not None:
        if outcome == "PROBATION":
            placement["is_on_probation"] = True
            domain.touch(placement)
        elif outcome == "EXITED":
            domain.run_exit_cascade(placement)
        # RETAINED: nothing further

    return success_object(serialize_reeval(reeval), 200)
