"""Evaluation endpoints (PRD §3.2)."""

from flask import Blueprint, request

import errors
from errors import ApiError
from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_int, require_enum
from services.common import new_record, touch, lookup, paginate, sorted_by_created
from services import serialize, calc

bp = Blueprint("evaluations", __name__)


@bp.route("/clinic/evaluations", methods=["POST"])
@require_roles("Evaluator")
def create_evaluation(user_id=None, role=None):
    body = get_body()
    child_id = require_str_field(body, "child_id")
    discipline = require_enum(body, "discipline", {"SLP", "OT"})
    severity = require_int(body, "severity_score", minimum=0, maximum=100)
    # FK existence (PRD §2.5).
    lookup(db.children, child_id)
    rec = new_record({
        "child_id": child_id,
        "evaluator_id": user_id,   # X-User-ID of the acting Evaluator.
        "discipline": discipline,
        "severity_score": severity,
        "recommended_weekly_minutes": None,
        "status": "DRAFT",
    })
    db.evaluations[rec["id"]] = rec
    return success(serialize.evaluation(rec), status=201)


@bp.route("/clinic/evaluations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_evaluations(user_id=None, role=None):
    items = list(db.evaluations.values())
    for field in ("child_id", "evaluator_id", "discipline", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [e for e in items if e[field] == val]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.evaluation(e) for e in page], limit, offset, total)


@bp.route("/clinic/evaluations/<evaluation_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_evaluation(evaluation_id, user_id=None, role=None):
    rec = lookup(db.evaluations, evaluation_id)
    return success(serialize.evaluation(rec), status=200)


@bp.route("/clinic/evaluations/<evaluation_id>/finalize", methods=["POST"])
@require_roles("Evaluator")
def finalize_evaluation(evaluation_id, user_id=None, role=None):
    rec = lookup(db.evaluations, evaluation_id)
    # State: must be DRAFT.
    if rec["status"] != "DRAFT":
        raise ApiError(errors.ERR_EVALUATION_NOT_DRAFT, 409,
                       "Evaluation must be DRAFT to finalize.")
    child = lookup(db.children, rec["child_id"])
    if child["status"] != "ACTIVE":
        raise ApiError(errors.ERR_CHILD_DISCHARGED, 409,
                       "Child is DISCHARGED.")
    # Supersede prior FINALIZED evaluations for same child + discipline.
    for other in db.evaluations.values():
        if (
            other["id"] != rec["id"]
            and other["child_id"] == rec["child_id"]
            and other["discipline"] == rec["discipline"]
            and other["status"] == "FINALIZED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    rec["status"] = "FINALIZED"
    rec["recommended_weekly_minutes"] = calc.recommended_weekly_minutes(rec["severity_score"])
    touch(rec)
    return success(serialize.evaluation(rec), status=200)


def require_str_field(body, field):
    from validation import require_str
    return require_str(body, field)
