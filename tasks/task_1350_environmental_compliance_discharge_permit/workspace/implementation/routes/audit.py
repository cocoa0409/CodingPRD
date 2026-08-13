"""Audit log listing endpoint."""

from flask import Blueprint, request

import db
from middleware import require_roles
from response import list_success
from services.core import serialize_audit_entry, paginate

bp = Blueprint("audit", __name__)


@bp.route("/npdes/audit-entries", methods=["GET"])
def list_audit_entries():
    require_roles(["Any"])
    items = list(db.audit_entries)
    entity_type = request.args.get("entity_type")
    if entity_type:
        items = [e for e in items if e["entity_type"] == entity_type]
    entity_id = request.args.get("entity_id")
    if entity_id:
        items = [e for e in items if e["entity_id"] == entity_id]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_audit_entry(e) for e in page], total, limit, offset)
