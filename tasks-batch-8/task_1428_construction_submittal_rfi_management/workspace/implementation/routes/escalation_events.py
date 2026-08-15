"""EscalationEvent routes (append-only log reads)."""
from flask import Blueprint, request

from authz import ALL_ROLES, require_roles
from db import store
from errors import ApiError
from respond import success
from serialize import ser_escalation_event
from store_ops import paginate, sorted_by_creation

bp = Blueprint("escalation_events", __name__)


@bp.route("/v1/escalation-events", methods=["GET"])
def list_events():
    require_roles(ALL_ROLES)
    items = list(store.escalation_events.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [e for e in items if e["project_id"] == project_id]
    event_type = request.args.get("event_type")
    if event_type:
        items = [e for e in items if e["event_type"] == event_type]
    source_type = request.args.get("source_type")
    if source_type:
        items = [e for e in items if e["source_type"] == source_type]
    source_id = request.args.get("source_id")
    if source_id:
        items = [e for e in items if e["source_id"] == source_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_escalation_event(e) for e in page], response_type="array", pagination=pagination)


@bp.route("/v1/escalation-events/<eventId>", methods=["GET"])
def get_event(eventId):
    require_roles(ALL_ROLES)
    ev = store.escalation_events.get(eventId)
    if ev is None:
        raise ApiError("ERR_ESCALATION_EVENT_NOT_FOUND", 404, "Escalation event not found")
    return success(ser_escalation_event(ev))
