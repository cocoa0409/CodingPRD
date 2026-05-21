"""Routes: /fcra/candidates*."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_role, current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_candidate
from core.store import store
from core.utils import lock
from services.candidate_service import create_candidate, update_candidate
from services.validations import check_version, get_candidate_or_404


bp = Blueprint("candidates", __name__)


# POST /fcra/candidates
@bp.route("/fcra/candidates", methods=["POST"])
@require_roles("Recruiter")
def post_candidate():
    body = get_json_body()
    with lock():
        row = create_candidate(body)
    return success_response(serialize_candidate(row), status=201)


# GET /fcra/candidates/{candidateId}
@bp.route("/fcra/candidates/<candidate_id>", methods=["GET"])
@require_roles("Recruiter", "Adjudicator", "Candidate")
def get_candidate(candidate_id):
    cand = get_candidate_or_404(candidate_id)
    if current_role() == "Candidate" and current_user_id() != cand["id"]:
        from core.errors import err_forbidden

        raise err_forbidden("Candidates may only read their own row.")
    return success_response(serialize_candidate(cand))


# PATCH /fcra/candidates/{candidateId}
@bp.route("/fcra/candidates/<candidate_id>", methods=["PATCH"])
@require_roles("Recruiter")
def patch_candidate(candidate_id):
    cand = get_candidate_or_404(candidate_id)
    body = get_json_body()
    with lock():
        # OCC last per priority 20.
        if "version" in body:
            check_version(body.get("version"), int(cand["version"]))
        update_candidate(cand, body)
    return success_response(serialize_candidate(cand))


# GET /fcra/candidates
@bp.route("/fcra/candidates", methods=["GET"])
@require_roles("Recruiter", "Adjudicator")
def list_candidates():
    from flask import request

    limit, offset = parse_pagination()
    posture_filter = request.args.get("eligibility_posture")
    rows = [
        c
        for c in store.candidates.values()
        if c.get("archived_at") is None
        and (posture_filter is None or c.get("eligibility_posture") == posture_filter)
    ]
    rows.sort(key=lambda r: r["created_at"])
    sliced, pmeta = paginate(rows, limit, offset)
    return success_response(
        [serialize_candidate(r) for r in sliced],
        response_type="array",
        pagination=pmeta,
    )
