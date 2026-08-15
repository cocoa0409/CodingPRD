"""Positions, audit trail listing, and the desk logical clock."""
from flask import Blueprint, request

import db
import services as svc
from errors import raise_err
from middleware import (ALL_ROLES, AUDIT_READERS, body, paged, pagination,
                        require_roles)
from response import ok_list, ok_object
from util import parse_dt, public

bp = Blueprint("misc", __name__)


@bp.get("/trading/positions/<positionId>")
@require_roles(*ALL_ROLES)
def get_position(positionId):
    return ok_object(public(svc.fetch("positions", positionId, "ERR_POSITION_NOT_FOUND")))


@bp.get("/trading/positions")
@require_roles(*ALL_ROLES)
def list_positions():
    limit, offset = pagination()
    items = sorted(db.store["positions"].values(), key=lambda r: r["_seq"])
    account_id = request.args.get("account_id")
    security_id = request.args.get("security_id")
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if security_id is not None:
        items = [p for p in items if p["security_id"] == security_id]
    page, total = paged(items, limit, offset)
    return ok_list([public(p) for p in page], total, limit, offset)


@bp.get("/trading/audit-events")
@require_roles(*AUDIT_READERS)
def list_audit_events():
    limit, offset = pagination()
    items = sorted(db.store["audit_events"].values(), key=lambda r: r["_seq"])
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    if entity_type is not None:
        items = [e for e in items if e["entity_type"] == entity_type]
    if entity_id is not None:
        items = [e for e in items if e["entity_id"] == entity_id]
    page, total = paged(items, limit, offset)
    return ok_list([public(e) for e in page], total, limit, offset)


@bp.post("/trading/_clock/set_current_utc")
@require_roles("DeskAdmin")
def set_clock():
    b = body()
    raw = b.get("to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 datetime")
    if parsed <= db.clock_now():
        raise_err("ERR_INVALID_REQUEST", "The logical clock is monotone: to_iso8601 must be "
                                         "strictly later than the current value")
    db.clock_set(raw.strip())
    return ok_object({"current_utc": db.clock_raw()})
