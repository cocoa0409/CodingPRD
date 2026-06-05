"""Simulated clock route (test-driving). PRD §2.11."""
from flask import Blueprint

from db import store
from middleware import require_roles
from response import object_response
from services.common import get_json_body, require_fields, parse_iso_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("TestCenterAdmin", "ScoreOps", "Candidate", "AccommodationReviewer")
def set_clock():
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso_dt(body["to_iso8601"])
    store.set_clock_now(dt)
    # Endpoint output is null per scaffold; return empty object envelope.
    return object_response({}, 200)
