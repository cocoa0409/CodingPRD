from flask import Blueprint, request
from ..auth import require_role
from ..envelope import success
from ..errors import err
from ..clock import iso

bp = Blueprint("clock", __name__)


@bp.post("/api/_admin/reset")
def admin_reset():
    require_role("PlatformAdmin")
    from ..store import store
    from ..app import logical_clock
    store.reset()
    logical_clock.reset()
    return success({})


@bp.post("/api/_clock/advance")
def clock_advance():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    if "seconds" not in body:
        raise err("ERR_VALIDATION", "seconds is required")
    seconds = body["seconds"]
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise err("ERR_VALIDATION", "seconds must be a number")
    if seconds < 0:
        raise err("ERR_VALIDATION", "seconds must be non-negative")
    from ..app import logical_clock
    logical_clock.advance(seconds)
    # Sweep 60-second offer timeouts
    from ..domain.dispatch_sweep import sweep_expired_offers
    sweep_expired_offers()
    return success({"now": iso(logical_clock.now())})
