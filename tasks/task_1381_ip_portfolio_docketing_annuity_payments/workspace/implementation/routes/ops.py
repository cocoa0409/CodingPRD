"""Logical clock (PRD §2.4) and docket sweep (PRD §3.9) routes."""

from datetime import datetime, timezone

from flask import Blueprint

import db as dbmod
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles, get_json_body
from response import success_object
from services.common import check_allowed_fields
from services.cascade import run_sweep

bp = Blueprint("ops", __name__)


def _parse_iso8601(value, field):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, f"{field} must be an ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"{field} is not a valid ISO-8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt(dt):
    # PRD §2.4 represents the logical clock at seconds precision
    # ("reads exactly 2026-08-01T00:00:00Z").
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    check_allowed_fields(body, {"to_iso8601"})
    dt = _parse_iso8601(body.get("to_iso8601"), "to_iso8601")
    dbmod.DB["clock"] = dt
    return success_object({"current_utc": _fmt(dt)})


@bp.post("/docket-sweeps")
def docket_sweep():
    require_roles(["PlatformAdmin"])
    summary = run_sweep()
    return success_object(summary, 201)
