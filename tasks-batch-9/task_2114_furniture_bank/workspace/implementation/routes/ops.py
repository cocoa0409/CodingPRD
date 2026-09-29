"""Operational surface: the logical clock and the operational cycle (PRD 2.6)."""

from flask import Blueprint

from auth import authenticate
from core import clock
from envelope import object_response
from services.cycle import run_cycle
from validation import Field, validate_body

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(["PlatformAdmin"])
    payload = validate_body([Field("to_iso8601", "datetime")])
    clock.set(payload["to_iso8601"])
    return object_response({})


@bp.route("/_ops/run-cycle", methods=["POST"])
def ops_run_cycle():
    authenticate(["PlatformAdmin"])
    payload = validate_body([
        Field("advance_quota_epoch", "boolean", required=False, default=False),
    ])
    summary = run_cycle(bool(payload["advance_quota_epoch"]))
    return object_response(summary)
