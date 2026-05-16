"""POST /_clock/advance (Registrar) and POST /_sweep/no-show-and-promote."""

from flask import Blueprint, request

import clock as clock_mod
from errors import err_invalid_request
from middleware import require_roles
from response import iso_utc_ms, success
from services.common import get_json_body, parse_iso_or_400
from services.sweep_service import run_sweep
from services.test_event_service import advance_clock_for_all_events

bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("Registrar")
def clock_advance():
    body = get_json_body()
    to_raw = body.get("to")
    if not to_raw:
        raise err_invalid_request("'to' is required")
    new_instant = parse_iso_or_400(to_raw, "to")
    clock_mod.set_now(new_instant)
    advance_clock_for_all_events()
    return success({"now": iso_utc_ms(clock_mod.now())}, status=200)


@bp.route("/_sweep/no-show-and-promote", methods=["POST"])
@require_roles("Registrar", "Proctor")
def sweep():
    body = get_json_body()
    test_event_id = body.get("test_event_id")
    if not test_event_id:
        raise err_invalid_request("test_event_id is required")
    result = run_sweep(test_event_id)
    return success(result, status=200)
