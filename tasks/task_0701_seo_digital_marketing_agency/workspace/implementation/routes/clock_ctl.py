"""Logical-clock control endpoint (PRD §2.11).

Bootstrap endpoint: auth headers not required (priority-1 skip); priority-2 role
check still applies if a role header is supplied (AgencyAdmin only)."""
from flask import Blueprint, request

from auth import require_role, VALID_ROLES, Principal
from clock import parse_iso8601
from db import store
from errors import err
from helpers import get_body, require_str
from response import ok_empty

bp = Blueprint("clock_ctl", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role = request.headers.get("X-User-Role")
    if role is not None:
        if role not in VALID_ROLES:
            raise err("ERR_MISSING_AUTH", "Malformed X-User-Role header")
        require_role(Principal(request.headers.get("X-User-ID"), role), ["AgencyAdmin"])

    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    parsed = parse_iso8601(to_iso)
    if parsed is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO-8601 datetime")
    store.clock.set(parsed)
    return ok_empty(200)
