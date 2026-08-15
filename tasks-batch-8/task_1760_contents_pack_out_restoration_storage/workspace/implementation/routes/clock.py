"""Test-driving logical clock endpoint."""

from flask import Blueprint

from db import store, format_iso
from helpers import get_body, parse_iso8601
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "BillingClerk")
    body = get_body()
    to_iso8601 = body.get("to_iso8601")
    if to_iso8601 is None:
        from errors import validation
        raise validation("to_iso8601 is required")
    dt = parse_iso8601(to_iso8601)
    store.set_clock(dt)
    return success_object({"current_utc": format_iso(store.now())})
