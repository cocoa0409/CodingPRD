"""Logical clock endpoint."""

from __future__ import annotations

from flask import Blueprint, request

from core import run_clock_sweep
from db import _parse_iso, clock, iso_utc
from errors import invalid_request
from middleware import require_roles
from response import success_object
from validators import reject_unknown_fields, req_str, require_fields, require_object

bp = Blueprint("clock", __name__)


@bp.route("/hazwaste/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("EHSManager", "WasteCoordinator", "ComplianceAuditor")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"to_iso8601"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["to_iso8601"])
    s = req_str(body, "to_iso8601")
    try:
        dt = _parse_iso(s)
    except Exception:
        raise invalid_request("to_iso8601 must be ISO 8601")
    clock.set(dt)
    run_clock_sweep()
    return success_object({"current_utc": iso_utc(clock.now())})
