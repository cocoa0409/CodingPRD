"""Test-driving logical clock (PRD §2.5)."""

from flask import Blueprint

from db import db, parse_ts, format_ts
from errors import err, ERR_VALIDATION
from middleware import require_roles, get_json_body, require_fields, optional_fields_present
from response import success_object
from services.domain import fire_auto_transitions

bp = Blueprint("clock", __name__)


@bp.post("/engagement/_clock/set_current_utc")
def set_current_utc():
    require_roles("HRAdmin")
    body = get_json_body()
    optional_fields_present(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    try:
        to_dt = parse_ts(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "to_iso8601 must be an ISO 8601 timestamp", 400)
    db.clock = to_dt
    fire_auto_transitions()
    return success_object({"current_utc": format_ts(db.clock)})
