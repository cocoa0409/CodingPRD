"""The logical UTC clock (PRD 2.4), mounted outside the business prefix."""

from flask import Blueprint

import auth
import responses
import shapes
import store

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth.authorize("ProgramAdmin")
    data = shapes.body()
    instant = shapes.req_ts(data, "to_iso8601")
    store.set_logical(instant)
    return responses.object_response({"current_utc": store.iso(store.now_logical())})
