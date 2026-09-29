"""The logical-clock control endpoint (outside the business prefix)."""
from flask import Blueprint

import db
import middleware
import response
from services import validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@bp.post("/fleetcare/_clock/set_current_utc")
def set_current_utc():
    middleware.auth(*middleware.ALL_ROLES)
    body = middleware.body()
    moment = validate.instant(body, "to_iso8601")
    adopted = db.set_now(moment)
    return response.object_response({"current_utc": db.iso(adopted)})
