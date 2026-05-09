"""Internal test-driving endpoints: clock advance and synthetic event emit."""
from __future__ import annotations

from flask import Blueprint

from errors import APIError, ERR_VALIDATION
from middleware import require_roles
from response import success
from services.clock_advance import advance_to
from utils import get_body, iso_format, parse_iso, require_field

bp = Blueprint("test_drive", __name__)


@bp.post("/_clock/advance")
@require_roles("PropertyManager")
def clock_advance():
    body = get_body()
    to = require_field(body, "to")
    target = parse_iso(to, field="to")
    advance_to(target)
    return success({"clock": iso_format(target)})


@bp.post("/_events/emit")
@require_roles("PropertyManager")
def emit_event():
    body = get_body()
    source = require_field(body, "source")
    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        raise APIError(ERR_VALIDATION, "payload must be an object.", 422)
    # Synthetic event passthrough — accepted asynchronously per PRD §4 (HTTP 202).
    return success({"source": source, "accepted": True}, status=202)
