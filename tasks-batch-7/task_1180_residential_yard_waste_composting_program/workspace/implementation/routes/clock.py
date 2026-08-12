"""Logical clock endpoint (PRD §2.4)."""

from flask import Blueprint, request

from db import STORE, _parse_dt
from errors import err_invalid_request
from middleware import require_roles
from response import success_object
from services.validate import require_body, check_unknown_fields, req_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("ProgramAdmin")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"to_iso8601"})
    iso = req_str(data, "to_iso8601")
    try:
        _parse_dt(iso)
    except Exception:
        raise err_invalid_request("to_iso8601 must be an ISO 8601 UTC datetime")
    STORE.set_clock(iso)
    return success_object({})
