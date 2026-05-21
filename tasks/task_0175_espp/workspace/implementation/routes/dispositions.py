"""Disposition routes."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.serializers import disposition_view
from services.disposition_service import (
    create_disposition,
    get_disposition_or_404,
    patch_disposition,
    void_disposition,
)


bp = Blueprint("dispositions", __name__)


@bp.route("/dispositions", methods=["POST"])
@require_roles("Participant")
def post_disposition():
    payload = get_json_body()
    d = create_disposition(acting_user_id=current_user_id(), payload=payload)
    return success_response(disposition_view(d), status=201)


@bp.route("/dispositions/<disposition_id>", methods=["GET"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def get_one(disposition_id: str):
    d = get_disposition_or_404(disposition_id)
    return success_response(disposition_view(d))


@bp.route("/dispositions/<disposition_id>", methods=["PATCH"])
@require_roles("Participant")
def patch_one(disposition_id: str):
    payload = get_json_body()
    d = patch_disposition(
        disposition_id=disposition_id,
        acting_user_id=current_user_id(),
        payload=payload,
    )
    return success_response(disposition_view(d))


@bp.route("/dispositions/<disposition_id>", methods=["DELETE"])
@require_roles("Participant")
def delete_one(disposition_id: str):
    void_disposition(
        disposition_id=disposition_id, acting_user_id=current_user_id()
    )
    # 204 No Content — but we still send the envelope per the PRD's
    # convention. The PRD's §4 paragraph says delete returns 204 because the
    # body would be redundant; we follow that.
    from flask import Response

    return Response(status=204)
