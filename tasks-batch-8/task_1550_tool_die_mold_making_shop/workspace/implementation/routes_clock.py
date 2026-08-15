"""Logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

from store import STORE
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, fmt_dt)
from domain import sweep_all_customers

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(roles=["ShopAdmin"])
def set_clock(uid, role):
    data = validate_payload(get_body(), [
        ("to_iso8601", "datetime", True),
    ])
    target = data["to_iso8601"]
    if target < STORE.clock:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422,
                       "The logical clock must not move backward")
    STORE.clock = target
    sweep_all_customers()
    return ok({"current_utc": fmt_dt(STORE.clock)})
