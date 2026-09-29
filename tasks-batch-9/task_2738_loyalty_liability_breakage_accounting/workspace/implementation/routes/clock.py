"""The logical clock control endpoint (PRD §2.4)."""
from flask import Blueprint

from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_PROGRAM_ADMIN,
                  authorize)
from response import ok
from util import clock
from validate import field_datetime, json_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize(ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
    body = json_body()
    current_utc = field_datetime(body, "current_utc")
    clock.set(current_utc)
    return ok({})
