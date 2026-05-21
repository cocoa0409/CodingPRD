"""Server-clock endpoints (PRD §2.5)."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..errors import err_bad_request
from ..services.clock_sweep import run_sweep
from ..store import store
from ..util import format_iso8601, parse_iso8601
from ._helpers import get_json_body, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles(["TestDriver"])
def advance_clock():
    body = get_json_body()
    raw = require_field(body, "to_instant")
    try:
        target = parse_iso8601(raw)
    except Exception:
        raise err_bad_request("to_instant must be ISO 8601")

    s = store()
    if target < s.now():
        raise err_bad_request("to_instant must be >= current clock")

    s.set_now(target)
    run_sweep()

    return jsonify(success_object({"now": format_iso8601(s.now())})), 200


@bp.route("/_clock", methods=["GET"])
@require_roles([
    "TestDriver", "ElectionBoard", "RegistrarClerk",
    "ReviewerClerk", "PrecinctOfficer", "Voter",
])
def get_clock():
    s = store()
    return jsonify(success_object({"now": format_iso8601(s.now())})), 200
