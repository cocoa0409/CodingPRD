"""Test-driving logical clock endpoints (PRD §2.8, §3.7)."""

from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_json_body
from response import empty_response
from services.common import require_str
from clock import parse_iso
from services.order_ops import run_expiry_sweep

bp = Blueprint("clock", __name__)


def _authorize_admin():
    # Clock endpoints are exempt from authentication (PRD §2.1) but role-gated to
    # PlatformAdmin when a role is supplied.
    role = request.headers.get("X-User-Role")
    if role is not None and role != "PlatformAdmin":
        raise err("ERR_UNAUTHORIZED",
                  "role %s is not permitted for this endpoint" % role)


@bp.post("/_clock/set")
def clock_set():
    _authorize_admin()
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO-8601")
    db.clock.set(dt)
    return empty_response()


@bp.post("/_clock/advance")
def clock_advance():
    _authorize_admin()
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO-8601")
    db.clock.set(dt)
    run_expiry_sweep()
    return empty_response()
