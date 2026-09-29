"""The logical clock. No authentication headers are required here."""

from flask import Blueprint

from db import db
from response import object_response
from util import fmt_instant
from validation import f, validate_body

bp = Blueprint("clock", __name__)

CLOCK_SET = [f("current_utc", "instant", required=True)]


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = validate_body(CLOCK_SET)
    db.clock = body["current_utc"]
    return object_response({"current_utc": fmt_instant(db.clock)})
