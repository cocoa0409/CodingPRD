"""/drivers/{id}/duty-events endpoints."""

from __future__ import annotations

from flask import Blueprint, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import ApiError, ERR_NOT_FOUND
from ..serializers import serialize_duty_event
from ..services.duty_events import append_duty_event, edit_duty_event
from ..store import store
from ..timeutil import parse_iso
from ..util import get_pagination, paginate, require_json_body


duty_events_bp = Blueprint("duty_events", __name__)


@duty_events_bp.post("/drivers/<driver_id>/duty-events")
@require_auth({"Driver"})
def create_duty_event(driver_id: str):
    with store.lock:
        driver = store.drivers.get(driver_id)
        if driver is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
        payload = require_json_body()
        event = append_duty_event(driver, payload)
    return ok_object(serialize_duty_event(event), status=201)


@duty_events_bp.get("/drivers/<driver_id>/duty-events")
@require_auth({"Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def list_duty_events(driver_id: str):
    driver = store.drivers.get(driver_id)
    if driver is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")

    limit, offset = get_pagination()
    edit_state = flask_request.args.get("edit_state")
    from_str = flask_request.args.get("from")
    to_str = flask_request.args.get("to")
    daily_log_id = flask_request.args.get("daily_log_id")

    items = [e for e in store.duty_events.values() if e.get("driver_id") == driver_id]
    if edit_state:
        items = [e for e in items if e.get("edit_state", "ACTIVE") == edit_state]
    if daily_log_id:
        items = [e for e in items if e.get("daily_log_id") == daily_log_id]
    if from_str:
        try:
            from_dt = parse_iso(from_str)
            items = [e for e in items if parse_iso(e["event_time"]) >= from_dt]
        except Exception:
            pass
    if to_str:
        try:
            to_dt = parse_iso(to_str)
            items = [e for e in items if parse_iso(e["event_time"]) <= to_dt]
        except Exception:
            pass
    items.sort(key=lambda e: e["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_duty_event(e) for e in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )


@duty_events_bp.post("/drivers/<driver_id>/duty-events/<event_id>/edit")
@require_auth({"Driver"})
def edit_event(driver_id: str, event_id: str):
    with store.lock:
        driver = store.drivers.get(driver_id)
        if driver is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Driver not found.")
        payload = require_json_body()
        new_event = edit_duty_event(driver, event_id, payload)
    return ok_object(serialize_duty_event(new_event), status=201)
