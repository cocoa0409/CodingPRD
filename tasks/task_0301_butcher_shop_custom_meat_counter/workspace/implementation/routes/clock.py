"""Test-driving logical clock (PRD §3.9)."""
import db
import response
import validation as v
from middleware import authenticate, require_role
from services import common


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        body = v.get_body()
        to_iso = v.require(body, "to_iso8601")
        dt = common.parse_iso(to_iso, "to_iso8601")
        db.set_clock(dt)
        # output: null (SCAFFOLD §1.5) -> empty data object, 200.
        return response.object_response({}, 200)
