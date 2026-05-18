"""Logical clock advance endpoint."""

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles
from response import success
from routes._helpers import get_json_body, require_field
from services.sweep import sweep
from utils import parse_iso_datetime

clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/advance")
def advance_clock():
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    body = get_json_body()
    target_raw = require_field(body, "target_timestamp")
    if not isinstance(target_raw, str):
        raise_error("ERR_VALIDATION_FAILED", "target_timestamp must be an ISO 8601 string")
    try:
        target = parse_iso_datetime(target_raw)
    except Exception:
        raise_error("ERR_VALIDATION_FAILED", "target_timestamp must be an ISO 8601 string")

    with store.lock:
        store.clock.advance_to(target)
        sweep()

    return success({}, status_code=200)
