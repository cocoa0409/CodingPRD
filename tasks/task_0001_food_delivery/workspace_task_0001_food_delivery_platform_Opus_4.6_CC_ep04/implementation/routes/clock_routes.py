from flask import Blueprint, request
from middleware.auth import require_roles
from clock import logical_clock
from response import success_response
from errors import raise_error, ERR_VALIDATION
from services.dispatch import sweep_expired_offers

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/advance", methods=["POST"])
@require_roles("PlatformAdmin")
def advance_clock():
    data = request.get_json(force=True, silent=True) or {}
    seconds = data.get("seconds")
    if seconds is None or not isinstance(seconds, (int, float)) or seconds <= 0:
        raise_error(ERR_VALIDATION, "seconds must be a positive number.")

    new_time = logical_clock.advance(seconds)
    sweep_expired_offers(new_time)

    return success_response({
        "current_time": logical_clock.format_timestamp(new_time),
    })
