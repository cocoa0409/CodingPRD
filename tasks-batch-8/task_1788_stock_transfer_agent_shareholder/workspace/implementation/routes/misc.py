"""Audit chain query and logical clock test-driving endpoints."""
from flask import Blueprint, request

from db import AUDIT_EVENTS, set_clock
from errors import fail
from helpers import get_body, req_dt, pagination_params, fmt_dt
from middleware import auth, require_role
from response import success_list, success_object
from services import audit_event_view, evaluate_clock

bp = Blueprint("misc", __name__)


@bp.get("/audit-events")
def list_audit_events():
    user_id, role = auth()
    require_role(role, {"AgentAdmin", "ComplianceOfficer"})
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    items = sorted(AUDIT_EVENTS, key=lambda e: e["_seq"])
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    if entity_id is not None:
        items = [e for e in items if e["entity_id"] == entity_id]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([audit_event_view(e) for e in page], limit, offset, total)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    user_id, role = auth()
    require_role(role, {"AgentAdmin"})
    body = get_body()
    target = req_dt(body, "to_iso8601")
    set_clock(target)
    evaluate_clock(target, role, user_id)
    return success_object({"current_utc": fmt_dt(target)})
