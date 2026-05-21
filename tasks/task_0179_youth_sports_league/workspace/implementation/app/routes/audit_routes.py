"""Audit event listing."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_roles
from ..response import paginated_response
from ..services.serializers import serialize_audit
from ..store import get_store
from ..validation import parse_pagination

audit_bp = Blueprint("audits", __name__)


@audit_bp.route("/league/audit-events", methods=["GET"])
@require_roles(["LeagueAdmin"])
def list_audits():
    store = get_store()
    limit, offset = parse_pagination()
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    action = request.args.get("action")

    results = []
    for evt in store.audits:
        if entity_type and evt["entity_type"] != entity_type:
            continue
        if entity_id and evt["entity_id"] != entity_id:
            continue
        if action and evt["action"] != action:
            continue
        results.append(evt)
    results.sort(key=lambda x: x["created_at"])
    total = len(results)
    page = results[offset : offset + limit]
    return paginated_response([serialize_audit(x) for x in page], total, limit, offset)
