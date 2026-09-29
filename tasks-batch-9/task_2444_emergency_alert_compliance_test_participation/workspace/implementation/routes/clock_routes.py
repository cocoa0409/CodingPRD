"""POST /_clock/set_current_utc — the logical clock (PRD 2.4)."""

from flask import Blueprint, request

import clock
from auth import guard
from envelope import empty_response
from validators import json_body, req_datetime

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@guard("ComplianceAdmin")
def set_current_utc():
    body = json_body(request)
    to_iso8601 = req_datetime(body, "to_iso8601")
    clock.set_now(to_iso8601)
    # mutates no entity and fires no recompute event
    return empty_response(200)
