"""Logical clock + daily sweep endpoints."""

from flask import Blueprint

import db
from db import CLOCK
from middleware import authenticate
from response import success_object
from validate import get_body, validate_shape
from services.sweep import run_sweep

bp = Blueprint("ops", __name__)


@bp.route("/assistance/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["ProgramAdmin"])
    body = validate_shape(get_body(allow_empty=False),
                          [("to_iso8601", "datetime", True, None)])
    CLOCK.set(db.parse_datetime(body["to_iso8601"]))
    return success_object({"current_utc": CLOCK.now_iso()})


@bp.route("/assistance/ops/daily-sweep", methods=["POST"])
def daily_sweep():
    authenticate(["ProgramAdmin"])
    body = validate_shape(get_body(),
                          [("observed_low_f", "number", False, None),
                           ("observed_heat_index_f", "number", False, None)])
    tally = run_sweep(body.get("observed_low_f"), body.get("observed_heat_index_f"))
    return success_object(tally)
