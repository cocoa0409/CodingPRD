"""Test-driving clock endpoint. PRD §2.4 / §4."""
from __future__ import annotations

from flask import Blueprint

import db
from common import get_body, iso_format, parse_iso_datetime, require_field
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("Administrator")
def set_clock():
    body = get_body()
    pinned = parse_iso_datetime(require_field(body, "to_iso8601"), "to_iso8601")
    db.set_clock(pinned)
    return success({"now": iso_format(pinned)})
