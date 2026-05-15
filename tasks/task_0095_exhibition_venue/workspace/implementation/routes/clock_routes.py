"""Test-driving clock endpoint."""

from flask import Blueprint, g

import clock
import response as resp
from errors import AppError, ERR_INVALID_INPUT
from middleware import require_roles
from services import entitlement_service


bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def advance():
    require_roles("TestHarness")
    body = g.body or {}
    target = body.get("to")
    if not target:
        raise AppError(ERR_INVALID_INPUT, "Field 'to' is required.", 422)
    dt = clock.parse_iso(target)
    if dt is None:
        raise AppError(ERR_INVALID_INPUT, "Invalid 'to' timestamp.", 422)
    clock.advance_to(dt)
    # Cascade: auto-MISS entitlements whose deadlines have now passed.
    entitlement_service.clock_cascade(dt)
    return resp.success({"now": clock.iso()})
