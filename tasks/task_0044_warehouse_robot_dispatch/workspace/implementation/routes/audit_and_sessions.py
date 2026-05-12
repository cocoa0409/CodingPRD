"""Audit-events list and charging-session cancel endpoints."""
from __future__ import annotations

from flask import Blueprint, request, g

from db import db
from errors import raise_error
from middleware import require_roles
from response import success, list_response
from services.lookup import get_fleet_or_404, get_session_or_404
from services.pagination import parse_pagination, paginate
from services.serialize import audit_event_to_dict, charging_session_to_dict
from services.transitions import cancel_charging_session

audit_bp = Blueprint("audit", __name__)


@audit_bp.route("/fleets/<fleet_id>/audit_events", methods=["GET"])
def list_audit(fleet_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    limit, offset = parse_pagination()
    args = request.args
    event_kind = args.get("event_kind")
    subject_kind = args.get("subject_kind")
    subject_id = args.get("subject_id")
    items = [e for e in db.audit_events.values() if e["fleet_id"] == fleet_id]
    if event_kind:
        items = [e for e in items if e["event_kind"] == event_kind]
    if subject_kind:
        items = [e for e in items if e["subject_kind"] == subject_kind]
    if subject_id:
        items = [e for e in items if e["subject_id"] == subject_id]
    items.sort(key=lambda e: e["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [audit_event_to_dict(e) for e in page],
        total=total, limit=limit, offset=offset,
    )


@audit_bp.route("/fleets/<fleet_id>/charging_sessions/<session_id>:cancel", methods=["POST"])
def cancel_session(fleet_id, session_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    session = get_session_or_404(fleet_id, session_id)
    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] != session["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    if session["status"] in {"COMPLETED", "CANCELLED"}:
        raise_error("ERR_INVALID_STATE", "Charging session is already terminal")
    cancel_charging_session(session, fleet, g.user_role)
    return success(charging_session_to_dict(session))
