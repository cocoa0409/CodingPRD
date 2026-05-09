"""Test-driver endpoints (clock advance, event emission)."""

from datetime import datetime, timezone

from flask import Blueprint, g

from clock import clock
from common import get_json_body, require_field
from db import db
from errors import ERR_INVALID_INPUT, raise_error
from middleware import require_roles
from response import success
from services.audit_log import append_log


bp = Blueprint("test_driver", __name__)


def _parse_iso8601(s: str) -> float:
    if not isinstance(s, str):
        raise_error(ERR_INVALID_INPUT, "target_iso must be string")
    try:
        if s.endswith("Z"):
            s2 = s.replace("Z", "+00:00")
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        raise_error(ERR_INVALID_INPUT, "target_iso is not a valid ISO 8601 timestamp")


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("TestDriver")
def post_clock_advance():
    body = get_json_body()
    target_iso = require_field(body, "target_iso", str)
    target_epoch = _parse_iso8601(target_iso)
    if target_epoch < clock.now_epoch():
        raise_error(ERR_INVALID_INPUT, "target_iso must be >= current clock")
    clock.set_to(target_epoch)
    return success({"now": clock.now_iso()}, 200)


@bp.route("/_events/emit", methods=["POST"])
@require_roles("TestDriver")
def post_event_emit():
    body = get_json_body()
    event_type = require_field(body, "event_type", str)
    payload = body.get("payload", {})
    append_log(
        subject_type="EVENT", subject_id=event_type, action="UPDATE",
        actor_role=g.user_role, actor_id=g.user_id,
        before_snapshot={}, after_snapshot={"event_type": event_type, "payload": payload},
    )
    return success({"accepted": True}, 200)
