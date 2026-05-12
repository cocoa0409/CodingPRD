"""Audit log read endpoint."""

from flask import Blueprint, request

import db
import helpers
import response
import serializers
from middleware import auth_required


bp = Blueprint("audit_log", __name__, url_prefix="/supply-chain/audit-log")


@bp.route("", methods=["GET"])
@auth_required("PlatformAdmin", "FinanceController")
def list_entries():
    limit, offset = helpers.parse_pagination()
    items = list(db.audit_log_entries)
    target_type = request.args.get("target_type")
    target_id = request.args.get("target_id")
    action = request.args.get("action")
    if target_type:
        items = [e for e in items if e["target_type"] == target_type]
    if target_id:
        items = [e for e in items if e["target_id"] == target_id]
    if action:
        items = [e for e in items if e["action"] == action]
    items.sort(key=lambda e: e["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.audit_log_entry_dict(e) for e in page],
                            limit=limit, offset=offset, total_count=total)
