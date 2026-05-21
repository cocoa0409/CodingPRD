"""System endpoints: /_health and /_clock/advance."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..clock import format_datetime_ms, get_clock
from ..common import parse_json_body, require_str
from ..response import make_object_envelope
from ..services.leave_case_service import clock_sweep


bp_system = Blueprint("system", __name__)


@bp_system.route("/_health", methods=["GET"])
def health():
    payload = {
        "status": "ok",
        "now": format_datetime_ms(get_clock().get()),
    }
    return jsonify(make_object_envelope(payload)), 200


@bp_system.route("/_clock/advance", methods=["POST"])
@require_roles("ComplianceOfficer")
def advance(user_id: str, role: str):
    body = parse_json_body()
    to_ts = require_str(body, "to_timestamp")
    clock = get_clock()
    clock.advance_to(to_ts)
    fired = clock_sweep()
    return jsonify(make_object_envelope({
        "now": format_datetime_ms(clock.get()),
        "transitions_fired": fired,
    })), 200
