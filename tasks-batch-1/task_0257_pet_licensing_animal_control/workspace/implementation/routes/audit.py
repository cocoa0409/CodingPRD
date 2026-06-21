"""Audit trail endpoint (PRD §3.9, §4)."""
from flask import Blueprint, request

from db import db
from middleware import authenticate, require_role
from response import array_response
from services.reqs import paginate, parse_pagination
from services.views import audit_view

bp = Blueprint("audit", __name__)


@bp.route("/audit-events", methods=["GET"])
def list_audit():
    _, role = authenticate()
    # clerks and officers may read the trail (PRD §3.9)
    require_role(role, {"LicensingClerk", "AnimalControlOfficer"})
    limit, offset = parse_pagination()
    items = list(db.audit_events.values())
    for field in ("subject_entity", "subject_id"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    page, total = paginate(items, limit, offset)
    return array_response([audit_view(a) for a in page], limit, offset, total)
