from __future__ import annotations
from flask import Blueprint

from db import db, parse_iso, now_iso
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import require_roles
from response import ok
from routes._helpers import get_body, require_field
from services import sweep

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("StoreManager", "StoreClerk")
def set_clock():
    body = get_body()
    to_iso = require_field(body, "to_iso8601")
    try:
        new_clock = parse_iso(to_iso)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")
        return
    db.clock = new_clock
    sweep.run_sweeps()
    return ok({"current_utc": now_iso(db.clock)})
