"""PointsTransaction ledger views and admin adjustments."""

from __future__ import annotations

from flask import Blueprint, g, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store
from ..timeutil import clock, parse_iso
from ..services.common import (
    get_json_body, require_fields, parse_pagination, paginate, bump_version,
    get_member_or_404, enforce_member_ownership,
)
from ..services.serialize import serialize_points_transaction
from ..services import ledger


ledger_bp = Blueprint("ledger", __name__)


@ledger_bp.get("/members/<member_id>/points-transactions")
@require_roles("Member", "ProgramAdmin")
def list_points_transactions(member_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    limit, offset = parse_pagination()
    kind_f = request.args.get("kind")
    since_f = request.args.get("since")
    until_f = request.args.get("until")
    since_dt = None
    until_dt = None
    if since_f:
        try:
            since_dt = parse_iso(since_f)
        except Exception:
            raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid since timestamp.")
    if until_f:
        try:
            until_dt = parse_iso(until_f)
        except Exception:
            raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid until timestamp.")
    items = []
    for t in store.points_transactions.values():
        if t["member_id"] != member_id:
            continue
        if kind_f and t["kind"] != kind_f:
            continue
        if since_dt and t["created_at"] < since_dt:
            continue
        if until_dt and t["created_at"] > until_dt:
            continue
        items.append(t)
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_points_transaction(t) for t in page]
    return ok_array(data, limit, offset, total, has_more)


@ledger_bp.post("/members/<member_id>/points-transactions/adjustments")
@require_roles("ProgramAdmin")
def admin_adjustment(member_id):
    m = get_member_or_404(member_id)
    body = get_json_body()
    require_fields(body, "points_delta", "reason")
    if not isinstance(body["points_delta"], int) or isinstance(body["points_delta"], bool):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "points_delta must be an integer.")
    if not isinstance(body["reason"], str) or not body["reason"].strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "reason required.")
    now = clock.now()
    t = ledger.append(
        member_id=member_id,
        kind="ADMIN_ADJUSTMENT",
        points_delta=body["points_delta"],
        posted_at=now,
        now=now,
    )
    bump_version(m, now)
    return ok_object(serialize_points_transaction(t), 201)
