"""Clock endpoint — logical clock control for testing."""

from flask import Blueprint, request

from db import store
from errors import invalid_request
from middleware import require_roles
from response import success_object
from services.domain import sweep_clock
from timeutil import parse_iso, dt_to_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("OpsAdmin")
    data = request.get_json(silent=True) or {}
    if "to_iso8601" not in data:
        raise invalid_request("Missing required field: to_iso8601")
    target = parse_iso(data["to_iso8601"])
    if target is None:
        raise invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    store.set_clock(target)
    sweep_clock()
    return success_object({"now_utc": dt_to_iso(store.now())})
