"""Audit event endpoints."""

from flask import Blueprint, request
import db
from middleware import require_roles, parse_pagination
from response import success_list

bp = Blueprint("audit", __name__)


def _event_to_json(e):
    return {k: v for k, v in e.items()}


@bp.route("/audit-events", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer")
def list_audit_events():
    limit, offset = parse_pagination()
    items = list(db.audit_events)

    entity_type = request.args.get("entity_type")
    if entity_type:
        items = [e for e in items if e["entity_type"] == entity_type]

    entity_id = request.args.get("entity_id")
    if entity_id:
        items = [e for e in items if e["entity_id"] == entity_id]

    event_type = request.args.get("event_type")
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]

    # Always sorted created_at ASC
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_event_to_json(e) for e in page], limit, offset, total)
