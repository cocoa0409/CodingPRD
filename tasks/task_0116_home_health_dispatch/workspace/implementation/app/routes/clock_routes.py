"""ClockState endpoints — admin-only clock advance + everyone can read.

Per SCAFFOLD §1.5:
- POST /_clock/advance: PlatformAdmin only. Body: { target_date }. ERR_CLOCK_BACKWARDS
  if target_date < current_date.
- GET /_clock: PlatformAdmin, IntakeCoordinator, BillingSpecialist, FieldClinician.
"""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import clock_today_iso, parse_date, set_clock
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..services.serialize import clock_view
from ..store import get_lock, get_store, reset_store


bp = Blueprint("clock", __name__)


@bp.post("/__test__/reset")
def test_reset():
    """Test-only: wipe the in-memory store between tests.

    Not in the PRD's role matrix — this is a harness convention used by
    the runner's autouse conftest to keep tests independent. No auth
    required; the endpoint is namespaced under /__test__/.
    """
    with get_lock():
        reset_store()
    return jsonify({"ok": True}), 200


@bp.post("/_clock/advance")
@require_auth("PlatformAdmin")
def advance_clock():
    body = get_json_body()
    target = require_field(body, "target_date")
    target_d = parse_date(target)

    with get_lock():
        current = parse_date(clock_today_iso())
        if target_d < current:
            raise APIError("ERR_CLOCK_BACKWARDS", "target_date < current_date")
        set_clock(target)
        body, status = success_response(clock_view(get_store().clock), status=200)
    return jsonify(body), status


@bp.get("/_clock")
@require_auth("PlatformAdmin", "IntakeCoordinator", "BillingSpecialist", "FieldClinician")
def read_clock():
    body, status = success_response(clock_view(get_store().clock), status=200)
    return jsonify(body), status
