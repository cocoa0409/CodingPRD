"""The logical clock test-driving capability (PRD §2.4)."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_REQUEST, fail
from middleware import ROLE_ADMIN, authorize, get_body, req_str
from response import object_response
from util import parse_instant, render_instant

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(ROLE_ADMIN)
    body = get_body()
    raw = req_str(body, "to_iso8601")
    moment = parse_instant(raw)
    if moment is None:
        fail(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 instant.")
    store.clock = moment
    # The server renders its own reading rather than echoing the caller.
    return object_response({"current_utc": render_instant(store.clock)})
