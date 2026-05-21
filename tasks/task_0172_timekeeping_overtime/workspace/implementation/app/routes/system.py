"""System routes — health probe and test-driving clock endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..clock import get_clock, format_iso_ms
from ..errors import err_invalid_input
from ..response import make_object_envelope
from ._helpers import parse_json_body


bp_system = Blueprint("system", __name__)


@bp_system.route("/healthz", methods=["GET"])
def healthz():
    # Unauthenticated health probe — does not enforce auth headers.
    body = make_object_envelope({"status": "ok"})
    return jsonify(body), 200


@bp_system.route("/timekeeping/_clock/advance", methods=["POST"])
@require_roles("PayrollAdmin")
def clock_advance(actor_user_id: str, actor_role: str):
    payload = parse_json_body()
    seconds = payload.get("seconds")
    if not isinstance(seconds, int) or isinstance(seconds, bool):
        raise err_invalid_input("seconds must be an integer.")
    clock = get_clock()
    new_now = clock.advance(int(seconds))
    return (
        jsonify(make_object_envelope({"now": format_iso_ms(new_now)})),
        200,
    )


@bp_system.route("/timekeeping/_clock/set", methods=["POST"])
@require_roles("PayrollAdmin")
def clock_set(actor_user_id: str, actor_role: str):
    payload = parse_json_body()
    now_str = payload.get("now")
    if not isinstance(now_str, str) or not now_str:
        raise err_invalid_input("now must be a non-empty ISO 8601 string.")
    clock = get_clock()
    try:
        new_now = clock.set_to(now_str)
    except Exception as e:
        raise err_invalid_input(f"Invalid ISO 8601 timestamp: {e}")
    return (
        jsonify(make_object_envelope({"now": format_iso_ms(new_now)})),
        200,
    )
