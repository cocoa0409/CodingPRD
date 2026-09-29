"""The logical clock and the network housekeeping sweep."""

from flask import Blueprint

from db import db
from errors import ApiError
from middleware import authorize
from response import object_response
from timeutils import parse_instant
from validation import payload, req_string
from services import sweep

bp = Blueprint("system", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(["NetworkOperator"])
    body = payload()
    raw = req_string(body, "current_utc")
    target = parse_instant(raw)
    if target < db.clock:
        raise ApiError(
            "ERR_CLOCK_NOT_MONOTONIC",
            "The logical clock may only be moved forward or left where it is.",
        )
    db.clock = target
    return object_response({})


@bp.route("/network-sweeps", methods=["POST"])
def network_sweep():
    authorize(["NetworkOperator"])
    return object_response(sweep.run())
