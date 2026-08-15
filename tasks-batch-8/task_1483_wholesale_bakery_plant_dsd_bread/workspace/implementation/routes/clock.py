"""POST /_clock/set_current_utc"""

from flask import Blueprint

from middleware import get_auth, require_role
from helpers import body, req_field
from response import success_object
from services import clock as clock_service

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    data = body()
    to_iso8601 = req_field(data, "to_iso8601")
    dt = clock_service.set_clock(to_iso8601)
    current = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return success_object({"current_utc": current}, status=200)
