"""Logical clock and audit trail endpoints."""
from datetime import datetime, timezone
from flask import Blueprint

import db
from db import store
from errors import ApiError
from response import ok, paginate
from middleware import get_context, require_roles
from validation import parse_body
from services.pricing import run_expiry_sweep

bp = Blueprint("misc", __name__)


@bp.post("/fab/_clock/set_current_utc")
def set_clock():
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    body = parse_body({"to_iso8601": ("string", True, None)}, allow_empty=False)
    raw = body["to_iso8601"]
    parsed = raw
    if parsed.endswith("Z"):
        parsed = parsed[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(parsed)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db.LOGICAL_CLOCK = dt.astimezone(timezone.utc)
    run_expiry_sweep()
    return ok({"current_utc": db.iso_logical(db.LOGICAL_CLOCK)})


@bp.get("/fab/audit-events")
def list_audit_events():
    uid, role, _ = get_context()
    require_roles(["ShopManager"])
    rows = list(store.audit_events)
    for f in ("entity_type", "entity_id", "event_type"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)
