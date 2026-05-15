"""Clock endpoints — POST /_clock/advance, GET /_clock."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import set_clock
from ..errors import APIError
from ..responses import success_response
from ..services.sweeps import sweep_after_clock_advance
from ..store import get_lock, get_store
from ..validators import get_json_body, require_string


bp = Blueprint("clock", __name__, url_prefix="/enrollment/_clock")


@bp.route("", methods=["GET"])
@require_auth("SystemOperator", "DistrictAdmin", "FamilyUser")
def read_clock():
    body, status = success_response(get_store().clock, status=200, response_type="object")
    return jsonify(body), status


@bp.route("/advance", methods=["POST"])
@require_auth("SystemOperator")
def advance_clock():
    body = get_json_body()
    target_now = require_string(body, "target_now", min_len=1, max_len=64)
    with get_lock():
        set_clock(target_now)
        sweep_after_clock_advance()
        resp, status = success_response(get_store().clock, status=200, response_type="object")
    return jsonify(resp), status
