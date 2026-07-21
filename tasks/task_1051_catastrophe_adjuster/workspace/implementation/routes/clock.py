from flask import Blueprint

from core import require_ctx, get_body, respond, set_clock, current_clock, parse_dt, iso, ApiError

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_ctx({"DeskExaminer", "LicensingAdmin", "BillingManager"})
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing to_iso8601")
    try:
        dt = parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid to_iso8601")
    set_clock(dt)
    return respond({"current_utc": iso(current_clock())}, status=200, response_type="object")
