"""AnnotatorProfile endpoints."""

from flask import Blueprint, request

import db
from middleware import require_role
from response import success, success_list, parse_pagination
from errors import (
    raise_error,
    ERR_ANNOTATOR_NOT_FOUND,
    ERR_INVALID_PARAMETER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_PACKAGE_STATE_INVALID,
)
from services.serializers import annotator_view
from services.annotator import (
    initial_tier_from_score,
    apply_suspension_cascade,
    recompute_tier,
    should_suspend,
    projected_pass_rate,
)


bp = Blueprint("annotators", __name__)


def _get_annotator(annotator_id: str) -> dict:
    a = db.find_by_id("annotators", annotator_id)
    if not a:
        raise_error(ERR_ANNOTATOR_NOT_FOUND, "Annotator not found.")
    return a


@bp.route("/annotators", methods=["POST"])
def register_annotator():
    require_role("ProjectManager")
    body = request.get_json(silent=True) or {}
    display_name = body.get("display_name")
    if not display_name or not isinstance(display_name, str):
        raise_error(ERR_INVALID_PARAMETER, "display_name is required.")
    domain_tags = body.get("domain_tags")
    if not isinstance(domain_tags, list):
        raise_error(ERR_INVALID_PARAMETER, "domain_tags must be an array.")
    score = body.get("entry_test_score")
    if not isinstance(score, (int, float)) or score < 0 or score > 100:
        raise_error(ERR_INVALID_PARAMETER, "entry_test_score must be in [0, 100].")
    tier = initial_tier_from_score(score)
    a = db.insert("annotators", {
        "display_name": display_name,
        "domain_tags": list(domain_tags),
        "entry_test_score": score,
        "tier": tier,
        "lifetime_pass_rate": 1.0,
        "rolling_pass_rate": 1.0,
        "golden_hit_rate": 1.0,
        "status": "ACTIVE",
        "last_evaluated_at": None,
        "submitted_count": 0,
        "approved_count": 0,
        "outcome_history": [],
        "dispute_history": [],
    })
    return success(annotator_view(a), status_code=201)


@bp.route("/annotators", methods=["GET"])
def list_annotators():
    require_role("ProjectManager", "QAReviewer")
    limit, offset = parse_pagination(request.args)
    filters = {}
    tier = request.args.get("tier")
    if tier:
        filters["tier"] = tier
    status = request.args.get("status")
    if status:
        filters["status"] = status
    rows, total = db.query("annotators", filters=filters,
                           limit=limit, offset=offset)
    return success_list([annotator_view(r) for r in rows], total, limit, offset)


@bp.route("/annotators/<annotator_id>", methods=["GET"])
def read_annotator(annotator_id):
    require_role("ProjectManager", "QAReviewer", "Annotator")
    a = _get_annotator(annotator_id)
    return success(annotator_view(a))


@bp.route("/annotators/<annotator_id>/re-evaluate", methods=["POST"])
def reevaluate(annotator_id):
    require_role("ProjectManager")
    a = _get_annotator(annotator_id)
    if a.get("status") == "ACTIVE" and should_suspend(a):
        from services.package import _audit_package_status
        apply_suspension_cascade(a, write_log_fn=_audit_package_status)
    else:
        new_tier = recompute_tier(a) if a.get("status") == "ACTIVE" else a.get("tier")
        if new_tier and new_tier != a.get("tier"):
            db.update("annotators", annotator_id, {"tier": new_tier})
    db.update("annotators", annotator_id, {"last_evaluated_at": db.now_iso()})
    return success(annotator_view(db.find_by_id("annotators", annotator_id)))


@bp.route("/annotators/<annotator_id>/reinstate", methods=["POST"])
def reinstate(annotator_id):
    require_role("ProjectManager")
    a = _get_annotator(annotator_id)
    if a.get("status") != "SUSPENDED":
        raise_error(ERR_PACKAGE_STATE_INVALID, "Annotator not SUSPENDED.")
    db.update("annotators", annotator_id, {"status": "ACTIVE"})
    return success(annotator_view(db.find_by_id("annotators", annotator_id)))


@bp.route("/annotators/<annotator_id>/projected-pass-rate", methods=["GET"])
def get_projected(annotator_id):
    require_role("ProjectManager", "QAReviewer", "Annotator")
    _get_annotator(annotator_id)
    rates = projected_pass_rate(annotator_id)
    return success({"annotator_id": annotator_id, **rates})
