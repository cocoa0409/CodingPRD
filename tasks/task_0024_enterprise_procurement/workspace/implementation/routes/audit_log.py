"""Audit log query endpoint (PRD §2.11)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db, serialize_list, order_by_created_then_seq
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array

bp = Blueprint("audit_log", __name__)


@bp.get("/audit-log")
@require_roles("GeneralManager", "FinanceApprover", "LegalApprover")
def list_audit():
    limit, offset = parse_limit_offset()
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    action = request.args.get("action")
    rows = list(db.audit_log)
    if entity_type is not None:
        rows = [r for r in rows if r.get("entity_type") == entity_type]
    if entity_id is not None:
        rows = [r for r in rows if r.get("entity_id") == entity_id]
    if action is not None:
        rows = [r for r in rows if r.get("action") == action]
    rows = order_by_created_then_seq(rows)
    page, total = paginate(rows, limit, offset)
    return jsonify(success_array(serialize_list(page), limit, offset, total)), 200
