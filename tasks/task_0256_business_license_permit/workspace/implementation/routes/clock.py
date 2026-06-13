from flask import Blueprint

from db import store
import errors
import middleware
import response
from services import validate
from services.entities import parse_iso8601

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    data = validate.body()

    to_iso8601 = validate.require_str(data, "to_iso8601")
    try:
        dt = parse_iso8601(to_iso8601)
    except (ValueError, TypeError):
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 instant")

    store.clock_now = dt
    return response.object_response({}, 200)
