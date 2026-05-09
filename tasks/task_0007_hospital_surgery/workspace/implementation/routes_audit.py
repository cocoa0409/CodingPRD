from flask import Blueprint, request

from db import db
from middleware import auth_required
from response import success, paginate
from serialize import serialize_audit
from utils import get_pagination

bp = Blueprint("audit_entries", __name__)


@bp.route("/audit-entries", methods=["GET"])
@auth_required("Any")
def list_audit_entries():
    limit, offset = get_pagination()
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    action = request.args.get("action")
    with db.lock:
        items = sorted(db.audit_entries.values(), key=lambda r: (r["created_at"], r["_seq"]))
        if entity_type:
            items = [r for r in items if r["entity_type"] == entity_type]
        if entity_id:
            items = [r for r in items if r["entity_id"] == entity_id]
        if action:
            items = [r for r in items if r["action"] == action]
        sliced, pagination = paginate(items, limit, offset)
        data = [serialize_audit(r) for r in sliced]
    return success(data, response_type="array", pagination=pagination)
