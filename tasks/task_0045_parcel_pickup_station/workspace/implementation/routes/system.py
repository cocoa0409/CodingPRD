"""Test-driving + introspection endpoints (clock, sweep, courier inbound, audit, system events)."""
from flask import Blueprint, request, g
from response import ok_object, ok_array
from middleware import require_roles, get_auth
from services.common import parse_pagination, sort_by_created, emit_event
from services.reminder import run_sweep
from services.serialize import audit_event, system_event
from db import store
from clock import advance, now_iso


bp = Blueprint("system", __name__)


@bp.post("/_clock/advance")
@require_roles("PlatformAdmin")
def clock_advance():
    body = request.get_json(silent=True, force=True) or {}
    seconds = body.get("seconds", 0)
    try:
        seconds = float(seconds)
    except Exception:
        seconds = 0.0
    advance(seconds)
    from clock import now_iso as ni
    return ok_object({"now": ni()})


@bp.post("/_sweep/run")
@require_roles("PlatformAdmin", "Manager")
def sweep_run():
    body = request.get_json(silent=True, force=True) or {}
    station_id_filter = body.get("station_id") if isinstance(body, dict) else None
    user_id, role = get_auth()
    result = run_sweep(station_id_filter, actor_role=role, actor_id=user_id)
    return ok_object(result)


@bp.post("/_events/courier/inbound")
@require_roles("PlatformAdmin")
def courier_inbound_event():
    body = request.get_json(silent=True, force=True) or {}
    # No DB write; just emit outbox event
    emit_event("COURIER", "INBOUND_HANDSHAKE", "Parcel",
               body.get("tracking_number", "unknown"),
               payload={
                   "courier_company_id": body.get("courier_company_id"),
                   "tracking_number": body.get("tracking_number"),
                   "station_id": body.get("station_id"),
                   "recipient_phone": body.get("recipient_phone"),
                   "weight_grams": body.get("weight_grams"),
                   "size_class": body.get("size_class"),
               })
    return ok_object({"accepted_at": now_iso()})


@bp.get("/audit-events")
@require_roles("PlatformAdmin", "Manager")
def list_audit_events():
    limit, offset = parse_pagination(request.args)
    subject_kind = request.args.get("subject_kind")
    subject_id = request.args.get("subject_id")
    items = list(store.audit_events.values())
    if subject_kind:
        items = [i for i in items if i["subject_kind"] == subject_kind]
    if subject_id:
        items = [i for i in items if i["subject_id"] == subject_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([audit_event(i) for i in page], limit, offset, total)


@bp.get("/system-events")
@require_roles("PlatformAdmin")
def list_system_events():
    limit, offset = parse_pagination(request.args)
    target_system = request.args.get("target_system")
    event_name = request.args.get("event_name")
    subject_id = request.args.get("subject_id")
    items = list(store.system_events.values())
    if target_system:
        items = [i for i in items if i["target_system"] == target_system]
    if event_name:
        items = [i for i in items if i["event_name"] == event_name]
    if subject_id:
        items = [i for i in items if i["subject_id"] == subject_id]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array([system_event(i) for i in page], limit, offset, total)
