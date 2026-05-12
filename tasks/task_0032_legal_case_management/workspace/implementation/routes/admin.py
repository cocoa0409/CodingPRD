"""Test-driving endpoints (clock + sweep, SystemIntegrator only)."""

import clock
import errors
import helpers
import response
from flask import Blueprint
from middleware import auth_required
from services import sweeps


bp = Blueprint("admin", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@auth_required("SystemIntegrator")
def clock_advance():
    body = helpers.get_json_body()
    if "target_timestamp" not in body:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "target_timestamp is required.")
    try:
        target = clock.parse_iso(body["target_timestamp"])
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "target_timestamp must be ISO 8601.")
    clock.advance_to(target)
    summary = sweeps.run_all()
    return response.ok({
        "current_instant": clock.iso_format(clock.now()),
        **summary,
    })


@bp.route("/_sweep/run", methods=["POST"])
@auth_required("SystemIntegrator")
def sweep_run():
    summary = sweeps.run_all()
    return response.ok({
        "current_instant": clock.iso_format(clock.now()),
        **summary,
    })
