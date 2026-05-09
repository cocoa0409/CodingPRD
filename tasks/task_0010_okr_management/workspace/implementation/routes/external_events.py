"""ExternalEvent endpoints."""

from flask import Blueprint, request
import datetime as _dt

import db
from auth import require_role
from clock import now, format_ts, parse_ts
from envelope import success_object, success_array
from errors import ApiError
from serialize import s_event
from util import (get_json_body, parse_pagination, paginate, require_fields,
                  gen_id)


bp = Blueprint("external_events", __name__)

DEDUP_WINDOW_MINUTES = 60


@bp.post("/external-events")
def receive_event():
    require_role("PlatformAdmin")
    body = get_json_body()
    require_fields(body, "source_system", "external_event_id", "event_type", "payload")
    source = body["source_system"]
    eid = body["external_event_id"]
    etype = body["event_type"]
    payload = body["payload"]
    if source not in ("HR", "PROJECT_MGMT", "IM"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "source_system invalid")
    received_at = format_ts(now())
    # Compare at the same millisecond precision used for storage so a re-arrival
    # exactly DEDUP_WINDOW_MINUTES later (per the formatted received_at) is detected
    # as duplicate without floating-point drift.
    received_at_dt = parse_ts(received_at)
    # Dedup: prior event with matching (source, external_event_id) within 60 min closed window
    duplicate = None
    for ev in db.external_events.values():
        if ev["source_system"] == source and ev["external_event_id"] == eid:
            prior_dt = parse_ts(ev["received_at"])
            diff_seconds = abs((received_at_dt - prior_dt).total_seconds())
            if diff_seconds <= DEDUP_WINDOW_MINUTES * 60:
                duplicate = ev
                break
    if duplicate is not None:
        # Record DUPLICATE event then surface error
        dup = {
            "id": gen_id(),
            "created_at": received_at,
            "source_system": source,
            "external_event_id": eid,
            "event_type": etype,
            "payload": payload,
            "received_at": received_at,
            "processing_status": "DUPLICATE",
            "processed_at": None,
            "side_effect_summary": None,
        }
        db.external_events[dup["id"]] = dup
        raise ApiError("ERR_DUPLICATE_EVENT", 409, "event is duplicate within dedup window")
    # Process event (no domain effects in this test surface; mark PROCESSED)
    ev = {
        "id": gen_id(),
        "created_at": received_at,
        "source_system": source,
        "external_event_id": eid,
        "event_type": etype,
        "payload": payload,
        "received_at": received_at,
        "processing_status": "PROCESSED",
        "processed_at": received_at,
        "side_effect_summary": "no-op",
    }
    db.external_events[ev["id"]] = ev
    return success_object(s_event(ev), status=201)


@bp.get("/external-events")
def list_events():
    require_role("PlatformAdmin", "HRBP")
    limit, offset = parse_pagination()
    items = list(db.external_events.values())
    source = request.args.get("source_system")
    pstatus = request.args.get("processing_status")
    if source:
        items = [e for e in items if e["source_system"] == source]
    if pstatus:
        items = [e for e in items if e["processing_status"] == pstatus]
    items.sort(key=lambda e: e["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_event(e) for e in page], total, limit, offset)
