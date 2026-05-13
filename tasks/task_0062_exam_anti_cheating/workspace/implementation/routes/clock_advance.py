"""Clock advance + reset endpoints for TestHarness."""
from flask import Blueprint

import db
from clock import set_now_unix, reset_now, now_unix
from errors import err
from middleware import require_auth, get_json_body
from response import success
from services import clock_tick


bp = Blueprint("clock_advance", __name__)


@bp.post("/_clock/advance")
@require_auth(roles={"TestHarness"})
def advance_clock():
    body = get_json_body()
    to = body.get("to_unix_seconds")
    if not isinstance(to, int) or isinstance(to, bool):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "to_unix_seconds must be an integer")
    # Do not allow the clock to go backwards beyond what's reasonable;
    # tests advance monotonically.
    set_now_unix(int(to))
    clock_tick.tick_all()
    return success({"now_unix_seconds": now_unix()})


@bp.post("/_test/reset")
@require_auth(roles={"TestHarness"})
def reset_state():
    db.reset_all()
    reset_now()
    return success({"reset": True})
