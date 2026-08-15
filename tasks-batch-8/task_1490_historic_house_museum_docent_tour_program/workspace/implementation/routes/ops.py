"""System / test-driving endpoints: the logical clock and the periodic sweep."""
from flask import Blueprint

from db import fmt_dt, now, set_clock
from middleware import auth
from response import ok
from services import run_epoch
from util import body, req_iso_dt

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["MuseumAdmin"])
    data = body()
    _, dt = req_iso_dt(data, "to_iso8601")
    set_clock(dt)
    return ok({"current_utc": fmt_dt(now())})


@bp.post("/_ops/run_epoch")
def run_epoch_endpoint():
    auth(["MuseumAdmin"])
    expired_booking_count, lapsed_member_count = run_epoch()
    return ok(
        {
            "expired_booking_count": expired_booking_count,
            "lapsed_member_count": lapsed_member_count,
        }
    )
