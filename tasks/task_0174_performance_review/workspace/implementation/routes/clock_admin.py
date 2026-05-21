"""Logical clock admin endpoints (PRD §2.13, §3.8)."""

from flask import Blueprint

from clock import clock
from db import _format_iso, parse_iso, store
from errors import raise_err
from middleware import require_role
from response import ok
from services.audit import log_event

from . import _helpers as H

bp = Blueprint("clock_admin", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_role("Admin")
def advance_clock():
    with store.lock:
        body = H.get_body()
        target_raw = H.require_field(body, "to_datetime")
        try:
            target = parse_iso(target_raw)
        except Exception:
            raise_err("ERR_VALIDATION", "to_datetime must be ISO 8601 UTC.")
        try:
            now = clock.advance_to(target)
        except ValueError:
            raise_err("ERR_VALIDATION", "Clock can only move forward.")
        log_event("Clock", "clock", "clock.advance", payload=body)
        return ok({"now": _format_iso(now)})
