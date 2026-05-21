"""Routes: /fcra/verification-items*."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_role, current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_forbidden
from core.serializers import serialize_item
from core.store import store
from core.utils import lock
from services.item_service import return_item
from services.validations import get_item_or_404


bp = Blueprint("items", __name__)


@bp.route("/fcra/verification-items/<item_id>", methods=["GET"])
@require_roles("Recruiter", "Adjudicator", "Candidate", "Verifier")
def get_item(item_id):
    item = get_item_or_404(item_id)
    if current_role() == "Candidate":
        order = store.orders.get(item["order_id"])
        if order is None or order["candidate_id"] != current_user_id():
            raise err_forbidden("Candidates may only read their own items.")
    return success_response(serialize_item(item))


@bp.route("/fcra/verification-items/<item_id>/return", methods=["POST"])
@require_roles("Verifier")
def post_return_item(item_id):
    item = get_item_or_404(item_id)
    body = get_json_body()
    with lock():
        return_item(
            item, body, actor_role=current_role(), actor_user_id=current_user_id()
        )
    return success_response(serialize_item(item))
