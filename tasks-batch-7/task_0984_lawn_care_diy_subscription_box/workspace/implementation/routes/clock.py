from flask import Blueprint

from db import store
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import get_body, authenticate
from response import ok
from services import run_clock_sweeps
from util import parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601.strip():
        raise_err(ERR_INVALID_REQUEST, "Field 'to_iso8601' is required")
    target = parse_dt(to_iso8601, "to_iso8601")
    authenticate(["PlatformAdmin"])

    store.clock = target
    store.clock_raw = to_iso8601
    boxes_generated, add_ons_expired = run_clock_sweeps()
    return ok({
        "now_iso8601": store.clock_raw,
        "boxes_generated": boxes_generated,
        "add_ons_expired": add_ons_expired,
    })
