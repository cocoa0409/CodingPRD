"""Audit list route."""
from flask import Blueprint, request

from db import db
from middleware import require_role
from response import success_array
from services.common import get_site_or_404, paginate, parse_pagination
from services.serialize import serialize_audit

bp = Blueprint("audit", __name__)


@bp.route("/sites/<site_id>/audit", methods=["GET"])
def list_audit(site_id):
    require_role(["SiteManager", "Dispatcher"])
    get_site_or_404(site_id)
    limit, offset = parse_pagination()

    items = list(db.audit_for_site(site_id))
    action = request.args.get("action")
    target_id = request.args.get("target_id")
    if action:
        items = [a for a in items if a["action"] == action]
    if target_id:
        items = [a for a in items if a["target_id"] == target_id]

    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([serialize_audit(a) for a in page], limit, offset, total)
