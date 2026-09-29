"""Test-driving endpoint for the server's logical clock (PRD 2.4)."""

from flask import Blueprint

import auth
import db
import response
import validate
from routes.helpers import PREFIX

bp = Blueprint("clock", __name__)


@bp.route(PREFIX + "/_clock/set_current_utc", methods=["POST"])
@auth.endpoint(auth.ALL_ROLES)
def set_current_utc():
    body = validate.body()
    instant = validate.parse_instant("current_utc", validate.req_str(body, "current_utc"))
    db.set_clock(instant)
    # Moving the clock re-evaluates nothing; the next business call asks the question.
    return response.object_response({"current_utc": db.iso(instant)})
