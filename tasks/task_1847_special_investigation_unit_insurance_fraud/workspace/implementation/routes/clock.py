"""POST /siu/_clock/set_current_utc — the administrative logical clock (PRD §2.10)."""

from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_roles
from response import success_object
from util import get_json_body, require_ts

bp = Blueprint("clock", __name__)


@bp.post("/siu/_clock/set_current_utc")
@require_roles("SIUManager", "SIUComplianceOfficer")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    raw = require_ts(body, "to_iso8601")
    db.clock.set(db.parse_instant(raw), raw)
    return success_object({"now_iso8601": db.clock.raw})
