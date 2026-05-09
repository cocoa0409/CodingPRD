"""Audit log and outbox event routes."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db
from errors import ERR_INVALID_STATE, raise_api_error
from middleware import require_roles
from response import list_response, success_response
from services.common import (
    check_version,
    get_insurer_or_404,
    get_json_body,
    get_outbox_or_404,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("audit_outbox", __name__)


@bp.get("/insurers/<insurer_id>/audit_logs")
@require_roles("Auditor", "ClaimsAdmin")
def list_audit_logs(insurer_id: str):
    get_insurer_or_404(insurer_id)
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    action = request.args.get("action")

    items = [a for a in db.audit_logs.values() if a.get("insurer_id") == insurer_id]
    if subject_type is not None:
        items = [a for a in items if a.get("subject_type") == subject_type]
    if subject_id is not None:
        items = [a for a in items if a.get("subject_id") == subject_id]
    if action is not None:
        items = [a for a in items if a.get("action") == action]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return jsonify(list_response([dict(x) for x in page], limit, offset, total)), 200


@bp.get("/insurers/<insurer_id>/outbox_events")
@require_roles("ClaimsAdmin", "Auditor")
def list_outbox(insurer_id: str):
    get_insurer_or_404(insurer_id)
    limit, offset = parse_pagination()
    target_system = request.args.get("target_system")
    dispatch_status = request.args.get("dispatch_status")
    subject_id = request.args.get("subject_id")

    items = [e for e in db.outbox_events.values() if e.get("insurer_id") == insurer_id]
    if target_system is not None:
        items = [e for e in items if e.get("target_system") == target_system]
    if dispatch_status is not None:
        items = [e for e in items if e.get("dispatch_status") == dispatch_status]
    if subject_id is not None:
        items = [e for e in items if e.get("subject_id") == subject_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return jsonify(list_response([dict(x) for x in page], limit, offset, total)), 200


@bp.post("/insurers/<insurer_id>/outbox_events/<event_id>/mark_delivered")
@require_roles("ClaimsAdmin", "system")
def mark_delivered(insurer_id: str, event_id: str):
    get_insurer_or_404(insurer_id)
    ev = get_outbox_or_404(insurer_id, event_id)
    body = get_json_body()
    # Outbox entries are append-only (no version field). Skip OCC.
    if ev.get("dispatch_status") == "DELIVERED":
        # idempotent
        return jsonify(success_response(dict(ev))), 200
    if ev.get("dispatch_status") == "FAILED":
        raise_api_error(ERR_INVALID_STATE, "Cannot mark FAILED event as delivered.")
    ev["dispatch_status"] = "DELIVERED"
    return jsonify(success_response(dict(ev))), 200
