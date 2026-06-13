"""Logical clock test-driving endpoints (PRD 3.9)."""
from flask import Blueprint

from db import store
from middleware import require_roles
from response import success
from util import parse_dt
from services.common import get_body, require_fields
from services import license_ops

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
@require_roles("Clerk", "Registrar")
def set_clock():
    body = get_body()
    require_fields(body, "to_iso8601")
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    store.set_clock(dt)
    return success({}, status=200)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("Clerk", "Registrar")
def advance_clock():
    body = get_body()
    require_fields(body, "to_iso8601")
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    store.advance_clock(dt)
    license_ops.sweep_expired(dt)
    return success({}, status=200)
