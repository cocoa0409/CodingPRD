"""Logical clock control (PRD section 2.4)."""

from flask import Blueprint

import response
from db import db, lock
from middleware import OPERATOR_ROLES, authorize
from validate import body_of, req_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize(OPERATOR_ROLES)
    body = body_of()
    value = req_datetime(body, "current_utc")
    with lock:
        db.clock = value
    return response.ok({"current_utc": response.iso_ms(value)})
