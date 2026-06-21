"""Lessee endpoints — PRD §3.3, §4. Lessees are minted by application approval;
there is no create endpoint."""
from flask import Blueprint, request

import db
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import serialize, paginate, sort_by_created
from services import domain

bp = Blueprint("lessees", __name__)


@bp.get("/lessors/<lessor_id>/lessees/<lessee_id>")
def get_lessee(lessor_id, lessee_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_lessee(lessor_id, lessee_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/lessees")
def list_lessees(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        items = [l for l in db.lessees.values() if l["lessor_id"] == lessor_id]
        cred_app = request.args.get("credit_application_id")
        if cred_app is not None and cred_app != "":
            items = [l for l in items if l["credit_application_id"] == cred_app]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)
