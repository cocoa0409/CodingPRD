"""Clock endpoints (PRD §2.4)."""

import clock
import util
from errors import err_invalid_request
from middleware import require_roles
from response import success_object
from services import domain
from flask import Blueprint

bp = Blueprint("clock", __name__)


@bp.post("/carrier/_clock/set_current_utc")
@require_roles("ComplianceOfficer")
def set_current_utc(_user_id, _role):
    body = util.get_body()
    util.check_fields(body, required=["to_iso8601"])
    try:
        dt = util.parse_iso_instant(body["to_iso8601"])
    except ValueError:
        raise err_invalid_request("to_iso8601 must be an ISO-8601 UTC instant")
    clock.set_to(dt)
    domain.run_sweeps()
    return success_object({"current_utc": clock.format_current()}, 200)
