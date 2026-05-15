"""System endpoints: /_events/emit and /_clock/advance."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..store import store, fmt_ts
from ..utils import get_json_body, parse_iso_datetime, require_str


system_bp = Blueprint("system", __name__)


@system_bp.route("/_events/emit", methods=["POST"])
@require_auth(["PlatformAdmin"])
def emit_event():
    body = get_json_body()
    source_system = require_str(body, "source_system", min_len=1, max_len=200)
    payload = body.get("payload")
    if not isinstance(payload, (dict, list, str, int, float, bool)) and payload is not None:
        raise api_error("ERR_VALIDATION_FAILED", "payload must be a JSON value")

    with store.lock:
        # No organization context here — store as empty / null org id
        store.append_audit(
            organization_id="",
            actor_user_id=g.user_id,
            actor_role=g.user_role,
            event_type="EXTERNAL_SYNC",
            target_entity="ExternalEvent",
            target_id="",
            payload_json={"source_system": source_system, "payload": payload},
        )
    return success_envelope({"source_system": source_system, "received": True})


@system_bp.route("/_clock/advance", methods=["POST"])
@require_auth(["PlatformAdmin"])
def advance_clock():
    body = get_json_body()
    target = parse_iso_datetime(body.get("to_timestamp"))
    new = clock.advance_to(target)
    return success_envelope({"current_time": fmt_ts(new)})
