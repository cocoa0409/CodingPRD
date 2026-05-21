"""Purchase routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_response
from core.serializers import purchase_view
from services.purchase_service import (
    get_purchase_or_404,
    list_purchases_for_participant,
)


bp = Blueprint("purchases", __name__)


@bp.route("/purchases/<purchase_id>", methods=["GET"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def get_one(purchase_id: str):
    p = get_purchase_or_404(purchase_id)
    return success_response(purchase_view(p))
