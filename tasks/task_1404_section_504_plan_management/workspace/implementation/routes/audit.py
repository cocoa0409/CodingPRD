"""Compliance audit events: append-only ledger, list and detail."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success
from routes import list_response
from services import audit_event_out, get_audit_event

bp = Blueprint("audit", __name__)

AUDIT_READERS = ("District504Director", "Section504Coordinator", "SchoolPrincipal")


@bp.get("/audit-events")
@require_roles(*AUDIT_READERS)
def list_audit_events():
    items = list(db.audit_events.values())
    school_id = request.args.get("school_id")
    event_type = request.args.get("event_type")
    entity_ref = request.args.get("entity_ref")
    if school_id is not None:
        items = [e for e in items if e["school_id"] == school_id]
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    if entity_ref is not None:
        items = [e for e in items if e["entity_ref"] == entity_ref]
    return list_response(items, audit_event_out)


@bp.get("/audit-events/<eventId>")
@require_roles(*AUDIT_READERS)
def get_audit_event_detail(eventId):
    return success(audit_event_out(get_audit_event(eventId)), 200)
