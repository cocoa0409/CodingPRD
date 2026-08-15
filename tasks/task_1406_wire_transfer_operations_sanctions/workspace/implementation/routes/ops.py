"""Ops hooks: logical clock setter and audit log reads (PRD §2.5, §3.11)."""

from flask import Blueprint, request

from db import STORE, iso, now, parse_dt, pub
from errors import ERR_INVALID_REQUEST, ApiError
from listing import list_response
from middleware import AUDIT_READ, get_body, require_roles, validate_body
from response import ok
from services import get_or_404

bp = Blueprint("ops", __name__, url_prefix="/wire-ops")


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = require_roles("WireOpsAdmin")
    data = get_body()
    validate_body(data, {"to_iso8601": ("str", True, None)})
    try:
        target = parse_dt(data["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError(*ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO-8601 timestamp.")
    STORE.clock = target
    return ok({"current_utc": iso(now())})


@bp.get("/audit-logs")
def list_audit_logs():
    require_roles(*AUDIT_READ)
    items = list(STORE.audit_logs.values())
    wire_id = request.args.get("wire_id")
    entity_type = request.args.get("entity_type")
    if wire_id is not None:
        items = [e for e in items if e["wire_id"] == wire_id]
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    return list_response(items)


@bp.get("/audit-logs/<aid>")
def get_audit_log(aid):
    require_roles(*AUDIT_READ)
    entry = get_or_404(STORE.audit_logs, aid, "audit log entry")
    return ok(pub(entry))
