from flask import Blueprint

from db import store, parse_dt, iso
from errors import invalid_request
from middleware import require_roles
from response import success_object
from services.bids import sweep_expired_bids
from validate import Body, get_body

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles("FederationAdmin")
def set_clock():
    data = get_body()
    body = Body(data, {"to_iso8601"})
    to = body.req_datetime("to_iso8601")
    store.clock = parse_dt(to)
    sweep_expired_bids()
    return success_object({"current_utc": iso(store.clock)}, 200)
