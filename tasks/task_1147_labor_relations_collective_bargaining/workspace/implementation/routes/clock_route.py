"""Logical clock endpoint: POST /_clock/set_current_utc runs the epoch sweep."""

from flask import Blueprint

import clock
from helpers import authenticate, get_body, req_datetime
from response import success_object
from services import run_epoch_sweep

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["LRAdmin"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    clock.set_now(to_iso8601)
    transitioned = run_epoch_sweep(to_iso8601)
    return success_object({
        "current_utc": clock.iso_seconds(clock.now()),
        "transitioned": transitioned,
    })
