"""AuditEvent query endpoint (PRD §3.8)."""

from flask import Blueprint, request

from db import store
from errors import raise_err
from middleware import require_role
from response import ok, paginate
from services.serializers import audit_event_view

from . import _helpers as H

bp = Blueprint("audit_events", __name__)


@bp.route("/audit-events", methods=["GET"])
@require_role("Admin", "HRBP")
def list_audit_events():
    with store.lock:
        entity_type = request.args.get("entity_type")
        entity_id = request.args.get("entity_id")
        action = request.args.get("action")
        actor_user_id = request.args.get("actor_user_id")
        limit, offset = H.pagination_params()

        items = list(store.audit_events)
        if entity_type is not None:
            items = [a for a in items if a["entity_type"] == entity_type]
        if entity_id is not None:
            items = [a for a in items if a["entity_id"] == entity_id]
        if action is not None:
            items = [a for a in items if a["action"] == action]
        if actor_user_id is not None:
            items = [a for a in items if a["actor_user_id"] == actor_user_id]

        items.sort(key=lambda a: a["created_at"])
        sliced, page_meta = paginate(items, limit, offset)
        return ok([audit_event_view(a) for a in sliced], pagination=page_meta)
