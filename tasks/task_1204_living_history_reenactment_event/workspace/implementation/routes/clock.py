"""Test-driving logical clock endpoint."""

from flask import Blueprint, request

import db
from middleware import authenticate
from response import success
from util import body, fmt_dt, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["EventOrganizer"])
    to = req_dt(body(request), "to_iso8601")
    db.set_now(to)
    return success({"current_utc": fmt_dt(db.now())}, 200)
