"""Logical clock setter (PRD §2.11, §3.10 — BarnManager only)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from clock import parse_iso
from services.common import require_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = get_caller()
    require_role(caller, ["BarnManager"])
    body = request.get_json(silent=True) or {}
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO-8601 UTC")
    # records the supplied instant as current logical time; performs no other work
    # (no lazy waiver sweep) — PRD §3.10
    db.clock.set(dt)
    return success({}, 200)
