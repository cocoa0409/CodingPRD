"""Clock advance and sweep endpoints."""
from flask import Blueprint, g

from clock import set_now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services import sweep
from services.validation import get_body, require_field


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(roles={"Organizer"})
def clock_advance():
    body = get_body()
    require_field(body, "to")
    try:
        to_dt = parse_iso(body["to"])
    except ValueError:
        raise err("ERR_VALIDATION", "to must be ISO 8601")
    set_now(to_dt)
    # Per PRD §2.11, time-based auto-transitions are run by the separate
    # idempotent sweep capability. Clock advance only sets the logical clock;
    # tests / callers that want auto-transitions explicitly call /_sweep/run.
    return success({}, 200)


@bp.route("/_sweep/run", methods=["POST"])
@require_auth(roles={"Organizer"})
def run_sweep():
    sweep.run_sweep(g.user_id, g.user_role)
    sweep.run_sweep(g.user_id, g.user_role)
    return success({}, 200)
