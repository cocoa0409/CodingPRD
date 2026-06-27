"""Logical clock administration (PRD §2.9)."""
import errors
from clock import clock, parse_iso8601, format_iso8601_ms
from errors import err
from middleware import require_roles
from response import success
from services import recompute_all_active_notes
from validation import get_json


def register(app):

    @app.route("/_clock/set_current_utc", methods=["POST"])
    @require_roles("DealerAdmin")
    def set_clock():
        body = get_json()
        to_iso = body.get("to_iso8601")
        dt = parse_iso8601(to_iso)
        if dt is None:
            raise err(errors.ERR_INVALID_REQUEST,
                      "to_iso8601 must be an ISO 8601 instant.")
        clock.set(dt)
        # advancing the clock triggers a recompute of accrual/curtailment on
        # every ACTIVE/CURTAILMENT_DUE floor-plan note.
        recompute_all_active_notes()
        return success({"current_utc": format_iso8601_ms(dt)},
                       status=200, response_type="object")
