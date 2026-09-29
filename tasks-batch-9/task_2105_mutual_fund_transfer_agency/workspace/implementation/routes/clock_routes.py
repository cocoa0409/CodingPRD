"""The logical clock capability."""
from flask import Blueprint

import clock
import dates
import response
import validation
from errors import invalid
from middleware import ROLE_CO, ROLE_FA, ROLE_TAO, authenticate

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO))
    body = validation.body()
    if not validation.present(body, "to_iso8601"):
        raise invalid("Field 'to_iso8601' is required.")
    instant = dates.parse_instant(body["to_iso8601"])
    if instant is None:
        raise invalid("Field 'to_iso8601' must be an ISO 8601 instant.")
    clock.set_now(instant)
    return response.ok({"current_utc": clock.now_iso()})
