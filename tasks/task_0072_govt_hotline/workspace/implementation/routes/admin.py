"""Test-harness routes: /_clock/advance and /_sweep/run."""

from flask import Blueprint, request

from errors import AppError, ERR_VALIDATION, ERROR_STATUS
import db
import response as resp
import clock
from middleware import require_auth, require_role
from services import sweep as sweep_svc

bp = Blueprint("admin", __name__)


@bp.before_request
def auth():
    require_auth()


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_role("PlatformAdmin")
    body = request.get_json(force=True, silent=True) or {}
    seconds = body.get("seconds")
    if seconds is None or not isinstance(seconds, int) or isinstance(seconds, bool):
        raise AppError(ERR_VALIDATION, "seconds must be integer", ERROR_STATUS[ERR_VALIDATION])
    if seconds < 0:
        raise AppError(ERR_VALIDATION, "seconds must be >= 0", ERROR_STATUS[ERR_VALIDATION])
    clock.advance_seconds(seconds)
    return resp.success({
        "advanced_seconds": seconds,
        "offset_seconds": clock.get_offset_seconds(),
        "now": clock.now_iso(),
    })


@bp.route("/_sweep/run", methods=["POST"])
def sweep_run():
    require_role("PlatformAdmin")
    with db.LOCK:
        result = sweep_svc.run()
    return resp.success(result)
