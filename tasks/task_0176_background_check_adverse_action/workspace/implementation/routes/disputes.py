"""Routes: /fcra/disputes*."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_role, current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_forbidden
from core.serializers import serialize_dispute
from core.utils import lock
from services.dispute_service import open_dispute, resolve_dispute
from services.validations import get_dispute_or_404


bp = Blueprint("disputes", __name__)


@bp.route("/fcra/disputes", methods=["POST"])
@require_roles("Candidate")
def post_dispute():
    body = get_json_body()
    with lock():
        dispute = open_dispute(
            body=body, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_dispute(dispute), status=201)


@bp.route("/fcra/disputes/<dispute_id>", methods=["GET"])
@require_roles("Candidate", "Adjudicator")
def get_dispute(dispute_id):
    dispute = get_dispute_or_404(dispute_id)
    if current_role() == "Candidate" and dispute["candidate_id"] != current_user_id():
        raise err_forbidden("Candidates may only read their own disputes.")
    return success_response(serialize_dispute(dispute))


@bp.route("/fcra/disputes/<dispute_id>/resolve", methods=["POST"])
@require_roles("Adjudicator")
def post_resolve_dispute(dispute_id):
    dispute = get_dispute_or_404(dispute_id)
    body = get_json_body()
    with lock():
        resolve_dispute(
            dispute, body, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_dispute(dispute))
