"""Logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from services.cascades import run_clock_sweeps
from services.core import get_body, parse_dt_field
from util import CLOCK

bp = Blueprint("clock", __name__)


@bp.route("/vet/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorized(["SystemAdmin"])
    body = get_body()
    new_dt = parse_dt_field(body, "to_iso8601")
    CLOCK.set(new_dt.isoformat())
    run_clock_sweeps()
    return success_object({"current_utc": CLOCK.now_iso()})
