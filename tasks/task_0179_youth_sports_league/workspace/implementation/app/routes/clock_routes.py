"""Logical clock advance endpoint — test-only driver, auth exempt."""
from __future__ import annotations

from flask import Blueprint

from ..response import success_response
from ..time_utils import set_clock
from ..validation import as_iso_datetime, get_json_body, require_fields

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/advance", methods=["POST"])
def advance_clock():
    body = get_json_body()
    require_fields(body, ["to"])
    target = as_iso_datetime(body["to"], "to")
    set_clock(target)
    return success_response({}, status_code=200)
