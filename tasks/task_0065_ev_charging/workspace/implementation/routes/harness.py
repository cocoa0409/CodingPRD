"""Test-orchestration endpoints (clock advance, sweep, event emission)."""

from flask import Blueprint, g

import db
import clock
from clock import format_iso, now, now_iso, parse_iso
from errors import raise_error
from middleware import require_roles
from response import success
from services import dispatcher, sweep
from validators import parse_json_body


bp = Blueprint("harness", __name__)


VALID_SOURCES = {"PAYMENT", "MAPPING", "GRID"}


@bp.post("/_clock/advance")
@require_roles({"PlatformOperator"})
def clock_advance():
    body = parse_json_body()
    if "to_iso" in body and body["to_iso"] is not None:
        try:
            target = parse_iso(body["to_iso"])
        except Exception:
            raise_error("ERR_VALIDATION", "to_iso must be ISO 8601")
        clock.set_to(target)
    elif "advance_ms" in body and body["advance_ms"] is not None:
        ms = body["advance_ms"]
        if not isinstance(ms, int) or isinstance(ms, bool) or ms < 0:
            raise_error("ERR_VALIDATION", "advance_ms must be non-negative integer")
        clock.advance_ms(ms)
    else:
        raise_error("ERR_VALIDATION", "advance_ms or to_iso required")
    return success({"now": now_iso()})


@bp.post("/_sweep/run")
@require_roles({"PlatformOperator"})
def sweep_run():
    expired_ids = sweep.run_sweep()
    return success({"expired_reservation_ids": expired_ids})


@bp.post("/_events/emit")
@require_roles({"PlatformOperator"})
def emit_event():
    body = parse_json_body()
    source_system = body.get("source_system")
    event_type = body.get("event_type")
    payload = body.get("payload", {})
    if source_system not in VALID_SOURCES:
        raise_error("ERR_VALIDATION", "source_system invalid")
    if not isinstance(event_type, str) or not (1 <= len(event_type) <= 80):
        raise_error("ERR_VALIDATION", "event_type out of range")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise_error("ERR_VALIDATION", "payload must be object")

    record = {
        "source_system": source_system,
        "event_type": event_type,
        "payload": payload,
        "processed": False,
        "received_at": now_iso(),
    }
    db.append_only_record(record)
    db.external_events[record["id"]] = record

    dispatcher.dispatch(record, actor_id=g.user_id)
    return success(db.public(record))
