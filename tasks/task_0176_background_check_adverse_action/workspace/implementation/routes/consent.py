"""Routes: /fcra/candidates/{id}/consent + /consent/revoke."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_role, current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_forbidden
from core.serializers import serialize_consent
from core.utils import lock
from services.consent_service import record_consent, revoke_consent
from services.validations import get_candidate_or_404


bp = Blueprint("consent", __name__)


@bp.route("/fcra/candidates/<candidate_id>/consent", methods=["POST"])
@require_roles("Recruiter", "Candidate")
def post_consent(candidate_id):
    cand = get_candidate_or_404(candidate_id)
    if current_role() == "Candidate" and current_user_id() != cand["id"]:
        raise err_forbidden("Candidates may only record their own consent.")
    body = get_json_body()
    with lock():
        row = record_consent(
            candidate=cand,
            body=body,
            actor_role=current_role(),
            actor_user_id=current_user_id(),
        )
    return success_response(serialize_consent(row), status=201)


@bp.route("/fcra/candidates/<candidate_id>/consent/revoke", methods=["POST"])
@require_roles("Candidate")
def post_consent_revoke(candidate_id):
    cand = get_candidate_or_404(candidate_id)
    if current_user_id() != cand["id"]:
        raise err_forbidden("Candidates may only revoke their own consent.")
    with lock():
        row = revoke_consent(
            candidate=cand,
            actor_role=current_role(),
            actor_user_id=current_user_id(),
        )
    return success_response(serialize_consent(row))
