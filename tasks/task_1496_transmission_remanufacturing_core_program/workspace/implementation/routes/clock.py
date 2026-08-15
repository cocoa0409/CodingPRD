"""Logical clock endpoint (ProgramAdmin only)."""

from flask import Blueprint

from db import db
from middleware import require_role
from response import success
from validators import get_json_body, require_fields, parse_iso8601

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    require_role({"ProgramAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"], "to_iso8601")
    db.set_now(dt)
    return success({}, "object", 200)
