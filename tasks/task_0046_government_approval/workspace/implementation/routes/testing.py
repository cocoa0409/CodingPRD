"""Test-only clock and sweep endpoints."""

from flask import Blueprint, request

import db
from errors import AppError, ERR_VALIDATION_FAILED
from middleware import require_role
from response import success
from services import events

bp = Blueprint("testing", __name__)


@bp.post("/_clock/advance")
def advance():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    if "seconds" not in body or body["seconds"] is None:
        raise AppError(ERR_VALIDATION_FAILED, "seconds is required", 422)
    seconds = body["seconds"]
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise AppError(ERR_VALIDATION_FAILED, "seconds must be an integer", 422)
    if seconds < 0:
        raise AppError(ERR_VALIDATION_FAILED, "seconds must be >= 0", 422)
    db.advance_clock(seconds)
    return success({"now": db.now_iso(), "advanced_seconds": seconds}, 200)


@bp.post("/_sweep/run")
def sweep():
    require_role("PlatformAdmin")
    result = events.run_sweep()
    return success(result, 200)
