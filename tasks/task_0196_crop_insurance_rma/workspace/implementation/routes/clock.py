"""Server clock control (PRD §2.10)."""
from flask import Blueprint

import db
import response
from middleware import authenticate, require_role, get_json
from services.common import parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # POST /_clock/set_current_utc — RmaAdmin only (PRD §4)
    _, role = authenticate()
    require_role(role, {"RmaAdmin"})
    body = get_json()
    dt = parse_datetime(body, "to_iso8601", required=True)
    db.set_server_now(dt)
    # output: null -> empty object per envelope (PRD §2.2: 2xx with no data -> {})
    return response.success_object({}, 200)
