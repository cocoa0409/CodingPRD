"""POST /_clock/set_current_utc"""
from flask import Blueprint

from middleware import require_roles
from response import success_object
from errors import err_invalid_request, err_not_found
from util import parse_dt, iso_from_dt
from services.clock import set_logical_clock, get_logical_clock
from services.cascade import run_clock_cascades
from db import db
from ._helpers import get_json_body, require_fields

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 datetime")
    set_logical_clock(dt)
    run_clock_cascades()
    # PRD: output is Distributor. But this is global; return first distributor if any, else an empty pseudo.
    # Spec table says output: Distributor. Use the first created distributor when available.
    if db.distributors:
        # Return any one distributor's view (the clock is shared)
        first = next(iter(db.distributors.values()))
        first["logical_clock_utc"] = iso_from_dt(get_logical_clock())
        from services.core import serialize_distributor
        return success_object(serialize_distributor(first), 200)
    # No distributors yet — synthesize a minimal Distributor-shaped payload
    return success_object({
        "id": "",
        "name": "",
        "territory": "",
        "week_epoch": 0,
        "logical_clock_utc": iso_from_dt(get_logical_clock()),
        "lifecycle_posture": "ACTIVE",
    }, 200)
