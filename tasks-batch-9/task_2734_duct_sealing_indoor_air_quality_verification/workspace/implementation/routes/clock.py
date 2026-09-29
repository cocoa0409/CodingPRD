"""The administrative logical-clock capability (PRD section 2.4)."""

from flask import Blueprint

from envelope import object_response
from guard import ALL_ROLES, authenticate, body, vdt
from routes import PREFIX
from store import db, iso

bp = Blueprint("clock", __name__)


@bp.post(PREFIX + "/_clock/set_current_utc")
def set_current_utc():
    authenticate(ALL_ROLES)
    data = body()
    moment = vdt(data, "to_iso8601", required=True)
    # Mutates no entity and eagerly recomputes no derived field.
    db.clock = moment
    return object_response({"current_utc": iso(db.clock), "to_iso8601": iso(db.clock)})
