"""System endpoints: logical clock advancement."""
from __future__ import annotations

from flask import Blueprint

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_validation
from core.utils import parse_iso
from services.clock_service import set_now


bp = Blueprint("system", __name__)


@bp.post("/_clock/advance")
@require_roles("ADMIN")
def advance_clock():
    body = get_json_body()
    target = body.get("to")
    if target is None:
        raise err_validation("to is required.")
    try:
        dt = parse_iso(target)
    except ValueError as exc:
        raise err_validation(str(exc))
    set_now(dt)
    return success_response({})
