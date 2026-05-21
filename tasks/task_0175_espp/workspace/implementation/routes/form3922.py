"""Form 3922 routes — read-only and immutable."""
from __future__ import annotations

from flask import Blueprint

from core.auth import require_roles
from core.envelope import error_response, success_response
from core.serializers import form_3922_view
from services.form_service import get_form_or_404


bp = Blueprint("form3922", __name__)


@bp.route("/form-3922/<form_id>", methods=["GET"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def get_one(form_id: str):
    f = get_form_or_404(form_id)
    return success_response(form_3922_view(f))


# Explicit immutability handlers so any mutating verb returns
# ERR_FORM_3922_IMMUTABLE rather than a generic 405.
@bp.route("/form-3922/<form_id>", methods=["PATCH", "PUT", "DELETE"])
@require_roles("PlanAdministrator", "Participant", "TaxAuthority")
def reject_mutation(form_id: str):
    # Ensure the row exists first to fall through to immutability error.
    get_form_or_404(form_id)
    return error_response(
        "ERR_FORM_3922_IMMUTABLE",
        "Form 3922 is immutable.",
        409,
    )
