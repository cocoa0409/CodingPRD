from flask import Blueprint

import db
import errors
import services
from middleware import require_roles
from response import ok_object
from util import get_body, parse_dt_field

bp = Blueprint("clock", __name__)

COORD = "MedicalStaffCoordinator"


@bp.route("/mso/_clock/set_current_utc", methods=["POST"])
@require_roles(COORD)
def set_clock():
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "Missing required field: to_iso8601")
    dt = parse_dt_field(raw, "to_iso8601")
    db.set_clock(raw, dt)
    services.advance_clock()
    return ok_object({"current_utc": raw}, 200)
