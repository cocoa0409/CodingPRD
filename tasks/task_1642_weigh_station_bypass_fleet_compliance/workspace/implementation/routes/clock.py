"""Logical clock endpoint (PRD 2.4). PlatformAdmin only."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import body_json, ctx, require_role
from response import ok
from services.sweep import materialization_sweep
from util import fmt_ts, parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    _uid, role = ctx()
    require_role(role, ("PlatformAdmin",))
    body = body_json()
    target = parse_datetime(body.get("to_iso8601"))
    if target is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO-8601 timestamp"
        )
    store.clock = target
    tallies = materialization_sweep()
    return ok({"current_utc": fmt_ts(target), **tallies}, 200)
