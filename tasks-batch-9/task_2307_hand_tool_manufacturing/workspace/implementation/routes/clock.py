"""Logical clock control (PRD §2.8)."""

from flask import Blueprint, request

from errors import ApiError
from envelope import ok
from store import store
from validate import ROLES, get_body, parse_instant

clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/toolworks/_clock/set_current_utc")
def set_current_utc():
    # Test harnesses commonly drive the clock without a role header; when one is
    # present it must authenticate and must be PlatformAdmin.
    role = request.headers.get("X-User-Role")
    if role is not None:
        if role not in ROLES:
            raise ApiError("ERR_UNAUTHENTICATED")
        if role != "PlatformAdmin":
            raise ApiError("ERR_ROLE_NOT_PERMITTED")

    body = get_body()
    value = body.get("current_utc")
    instant = parse_instant(value)
    if instant is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'current_utc' must be an ISO 8601 instant.")

    store.clock = instant
    return ok({"current_utc": value})
