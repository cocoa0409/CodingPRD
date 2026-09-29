"""The logical clock (PRD section 2.4).

POST /_clock/set_current_utc is a PlantAdmin test affordance.  It returns 200,
modifies no entity, and is the only way the server's notion of "now" moves.
"""

from flask import Blueprint

import db
import middleware
import response
import validation

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = validation.body()
    if "current_utc" not in payload or payload["current_utc"] is None:
        raise validation.invalid("Field 'current_utc' is required.")
    parsed = validation.parse_iso_datetime("current_utc", payload["current_utc"])
    db.set_clock(parsed)
    return response.object_response({"current_utc": db.clock_now_iso()}, 200)
