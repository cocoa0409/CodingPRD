"""Administrative test-driving clock (PRD §3.3 / endpoint table).

POST /parking/_clock/set_current_utc fixes the server's notion of 'current UTC'
used by permit expiry, validation redemption, and LPR evaluation.
"""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import get_json_body, require_auth
from response import ok_object
from services.common import require_datetime

bp = Blueprint("clock", __name__)


@bp.post("/parking/_clock/set_current_utc")
def set_clock():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    to_iso8601 = require_datetime(body, "to_iso8601", required=True)
    db.set_current_utc(to_iso8601)
    # Output: null per the endpoint table -> empty object data payload.
    return ok_object({}, 200)
