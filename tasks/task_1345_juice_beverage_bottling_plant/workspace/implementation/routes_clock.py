"""Logical clock endpoint."""
from flask import Blueprint

from errors import err
from store import db, iso_ms
from util import body, ok, req_field, require_roles

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    require_roles("PlantManager")
    data = body()
    to_dt = req_field(data, "to_iso8601", "datetime")
    if to_dt < db.clock:
        raise err("ERR_CLOCK_REGRESSION",
                  "Cannot move the logical clock backwards")
    db.clock = to_dt
    return ok({"current_utc": iso_ms(db.clock)})
