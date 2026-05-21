"""POST /_clock/advance — admin-only logical-clock advance."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_roles
from ..envelope import ok_object
from ..services.common import get_json_body, require_fields
from ..timeutil import clock, iso_now
from .. import errors as E


clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/advance")
@require_roles("ProgramAdmin")
def advance_clock():
    body = get_json_body()
    require_fields(body, "by_seconds")
    by_seconds = body["by_seconds"]
    if not isinstance(by_seconds, int) or isinstance(by_seconds, bool):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "by_seconds must be an integer.")
    new_time = clock.advance(by_seconds)
    return ok_object({"current_time": iso_now(new_time)})
