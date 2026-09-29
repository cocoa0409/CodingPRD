"""The logical clock and its certificate-lapse cascade (PRD 2.10, 3.8)."""

from flask import Blueprint

from response import obj
from routes.common import authenticate
from services import cascades
from validators import json_body, req_instant

bp = Blueprint("clock", __name__)


@bp.post("/mill/_clock/set_current_utc")
def set_current_utc():
    authenticate(("PlantAdmin",))
    body = json_body()
    new_dt, new_raw = req_instant(body, "to_iso8601")
    return obj(cascades.advance_clock(new_dt, new_raw))
