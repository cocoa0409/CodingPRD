"""Logical clock + AuditEvent endpoints."""

from flask import Blueprint, request

import db
from errors import err_invalid_request
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import parse_iso8601, serialize
from services.sweeps import run_sweeps

bp = Blueprint("misc", __name__)


@bp.post("/stairlift-ops/_clock/set_current_utc")
def set_clock():
    require_role("PlatformAdmin")
    body = get_json_body(["to_iso8601"])
    target = body["to_iso8601"]
    dt = parse_iso8601(target)
    if dt is None:
        raise err_invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    db.set_now(dt)
    run_sweeps()
    return success_object({"now_iso8601": db.now_iso()})


@bp.get("/stairlift-ops/audit-events")
def list_audit_events():
    require_role("PlatformAdmin")
    limit, offset = get_pagination()
    entity_kind = request.args.get("entity_kind")
    entity_id = request.args.get("entity_id")
    items = sorted(db.audit_events.values(), key=lambda e: e["created_at"])
    if entity_kind:
        items = [e for e in items if e["entity_kind"] == entity_kind]
    if entity_id:
        items = [e for e in items if e["entity_id"] == entity_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(e) for e in page], limit, offset, total)
