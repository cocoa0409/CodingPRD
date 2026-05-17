"""Evaluation endpoints (create / finalize / amend)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_THERAPIST, require_roles
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_episode_or_404, get_evaluation_or_404
from ..services.mutations import (
    amend_evaluation,
    create_evaluation,
    finalize_evaluation,
)
from ..services.serialize import evaluation_to_dict
from ..store import store

bp = Blueprint("evaluations", __name__)

EVAL_TYPES = ["INITIAL", "REEVAL"]
COMPLEXITIES = ["LOW", "MODERATE", "HIGH"]


@bp.route("/episodes/<eid>/evaluations", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def create_evaluation_route(eid: str, **_kwargs):
    body = require_json_object()
    eval_type = assert_enum(body.get("evaluation_type"), "evaluation_type", EVAL_TYPES)
    clinician_id = assert_string(body.get("clinician_id"), "clinician_id")
    complexity = assert_enum(body.get("complexity"), "complexity", COMPLEXITIES)
    score = assert_integer(body.get("functional_baseline_score"), "functional_baseline_score", minimum=0, maximum=100)
    s = store()
    with s.lock:
        episode = get_episode_or_404(eid)
        row = create_evaluation(episode, eval_type, clinician_id, complexity, score)
    return created(evaluation_to_dict(row))


@bp.route("/evaluations/<evid>/finalize", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def finalize_evaluation_route(evid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    s = store()
    with s.lock:
        evaluation = get_evaluation_or_404(evid)
        occ_check(body.get("version"), evaluation["version"])
        row = finalize_evaluation(evaluation, _caller_id)
    return ok(evaluation_to_dict(row))


@bp.route("/evaluations/<evid>/amend", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def amend_evaluation_route(evid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    new_score = body.get("functional_baseline_score")
    if new_score is not None:
        assert_integer(new_score, "functional_baseline_score", minimum=0, maximum=100)
    new_complexity = body.get("complexity")
    if new_complexity is not None:
        assert_enum(new_complexity, "complexity", COMPLEXITIES)
    s = store()
    with s.lock:
        evaluation = get_evaluation_or_404(evid)
        occ_check(body.get("version"), evaluation["version"])
        row = amend_evaluation(evaluation, _caller_id, new_score, new_complexity)
    return ok(evaluation_to_dict(row))
