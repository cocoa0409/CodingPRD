from flask import Blueprint

from clock import CLOCK, parse_iso8601, iso_display
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import object_response
from validation import Payload

bp = Blueprint("clock", __name__, url_prefix="/legal-ops/_clock")


@bp.post("/set_current_utc")
@require_roles("LegalOpsManager")
def set_current_utc(user_id, role):
    p = Payload()
    raw = p.req_str("to_iso8601")
    p.finish()
    dt = parse_iso8601(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO 8601 timestamp")
    CLOCK.set(dt)
    return object_response({"current_utc": iso_display(CLOCK.now())})
