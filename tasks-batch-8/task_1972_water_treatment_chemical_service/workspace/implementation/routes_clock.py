"""Logical clock test-driving endpoint (PlatformAdmin)."""

from flask import Blueprint, g

from calc import run_sweeps
from db import set_clock, fmt_clock
from response import success_object
from validate import get_body, validate_shape

bp = Blueprint("clock", __name__)


@bp.route("/wt/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    body = get_body()
    vals = validate_shape(body, [("to_iso8601", "iso", True)])
    current = set_clock(vals["to_iso8601"])
    run_sweeps(current)
    return success_object({"current_utc": fmt_clock(current)}, 200)
