"""Test-driving logical clock. BranchManager-only; sweeps expired price books."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import require_roles, body
from response import ok
from routes.price_books import sweep_expired_books

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("BranchManager")
def set_current_utc():
    b = body()
    try:
        target = db.parse_dt(b.get("to_iso8601"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400,
                       "to_iso8601 must be an ISO 8601 datetime")
    db.set_clock(target)
    # Advancing the clock flips ACTIVE books whose window end was reached.
    sweep_expired_books()
    return ok({"current_utc": db.iso_logical(db.clock_now())})
