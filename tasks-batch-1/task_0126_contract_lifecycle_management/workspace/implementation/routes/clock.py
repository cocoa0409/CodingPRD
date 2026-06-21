"""Logical clock control (PRD §3.9)."""

from flask import Blueprint

from common import get_json_body, require_field
from middleware import require_roles
from response import success_object
from services.clock import advance_clock

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601", types=str)
    now_utc, swept_contract_ids = advance_clock(to_iso8601)
    data = {
        "now_utc": now_utc,
        "swept_contract_ids": swept_contract_ids,
    }
    return success_object(data, status=200)
