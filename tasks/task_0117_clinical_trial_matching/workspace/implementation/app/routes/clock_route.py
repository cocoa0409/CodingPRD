"""Test-only /_clock/advance endpoint."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_COORD, ROLE_IRB, ROLE_PI, require_roles
from ..clock import clock, iso_format
from ..errors import err_invalid_input
from ..helpers import parse_iso8601, require_json_object
from ..responses import ok
from ..store import reset_store

bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_roles(ROLE_PI, ROLE_COORD, ROLE_IRB)
def advance_clock(**_caller):
    body = require_json_object()
    target = parse_iso8601(body.get("to_iso8601"), "to_iso8601", required=True)
    try:
        new_now = clock.advance_to(target)
    except ValueError as ve:
        raise err_invalid_input(str(ve))
    return ok({"now": iso_format(new_now)})


@bp.post("/__test__/reset")
def test_reset():
    """Best-effort reset hook for the test conftest: wipe the in-memory
    store and reset the logical clock. Not part of PRD."""
    reset_store()
    return ok({"reset": True})
