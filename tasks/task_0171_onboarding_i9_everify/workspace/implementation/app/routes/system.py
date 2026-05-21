"""System test hooks: clock advance and sweep."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..clock import get_clock
from ..errors import err_validation
from ..response import make_object_envelope
from ..services.everify import run_sweep
from ._helpers import parse_json_body


bp_system = Blueprint("system", __name__)


@bp_system.route("/_clock/advance", methods=["POST"])
@require_roles("System")
def advance_clock_route(user_id, role):
    body = parse_json_body()
    to = body.get("to")
    if not isinstance(to, str) or not to:
        raise err_validation("'to' must be an ISO-8601 timestamp string.")
    clock = get_clock()
    try:
        clock.advance_to(to)
    except Exception as exc:
        raise err_validation(f"Invalid 'to' timestamp: {exc!r}")
    return jsonify(make_object_envelope(clock.to_view())), 200


@bp_system.route("/_sweep/run", methods=["POST"])
@require_roles("System")
def sweep_route(user_id, role):
    run_sweep(actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope({})), 200
