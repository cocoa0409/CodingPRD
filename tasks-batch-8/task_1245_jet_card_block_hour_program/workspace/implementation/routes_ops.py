"""Ops-run sweep and logical clock test-driving endpoints."""

from flask import Blueprint

from httpkit import (
    authenticate, ensure_empty_body, err_invalid_request, get_body,
    require_roles, respond_object,
)
from services import run_expiration_sweep
from store import db
from util import fmt_ts

bp = Blueprint("ops", __name__)


@bp.post("/ops/run")
def ops_run():
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    expired_ids, closed_ids = run_expiration_sweep()
    return respond_object({
        "expired_card_ids": expired_ids,
        "closed_card_ids": closed_ids,
        "expired_count": len(expired_ids),
        "closed_count": len(closed_ids),
        "current_utc": fmt_ts(db.now()),
    })


@bp.post("/_clock/set_current_utc")
def set_clock():
    data = get_body([
        {"name": "to_iso8601", "type": "datetime", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    target = data["to_iso8601"]
    if target < db.now():
        raise err_invalid_request("The logical clock only moves forward")
    db.clock = target
    return respond_object({"current_utc": fmt_ts(db.now())})
