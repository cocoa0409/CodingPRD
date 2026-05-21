from __future__ import annotations

from flask import Blueprint, g

from .. import projections, resolvers, return_logic
from ..auth import require_role
from ..envelope import err_forbidden, success
from ..store import store
from ..validators import get_json, require_int, require_str

bp = Blueprint("returns", __name__)


def _serialize(r: dict) -> dict:
    return projections.ret(r)


@bp.route("/api/orders/<oid>/returns", methods=["POST"])
def open_return(oid: str):
    require_role("Customer")
    o = resolvers.order(oid)
    if g.user_id != o["customer_id"]:
        raise err_forbidden("Customer identity mismatch")
    body = get_json()
    reason = body.get("reason")
    requested = body.get("requested_refund_cents")
    ret = return_logic.open_return(o, reason, requested)
    return success(_serialize(ret), status=201)


@bp.route("/api/returns/<rid>", methods=["GET"])
def read_return(rid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "CustomerService")
    r = resolvers.ret(rid)
    order = store.orders[r["order_id"]]
    if g.user_role == "Customer" and g.user_id != order["customer_id"]:
        raise err_forbidden("Customer identity mismatch")
    if g.user_role == "Restaurant" and g.user_id != order["restaurant_id"]:
        raise err_forbidden("Restaurant identity mismatch")
    return success(_serialize(r))


@bp.route("/api/returns/<rid>/approve", methods=["POST"])
def approve_return(rid: str):
    require_role("CustomerService")
    r = resolvers.ret(rid)
    body = get_json()
    approved = body.get("approved_refund_cents")
    return_logic.approve_return(r, approved, g.user_id)
    return success(_serialize(r))


@bp.route("/api/returns/<rid>/reject", methods=["POST"])
def reject_return(rid: str):
    require_role("CustomerService")
    r = resolvers.ret(rid)
    return_logic.reject_return(r, g.user_id)
    return success(_serialize(r))


@bp.route("/api/returns/<rid>/escalate", methods=["POST"])
def escalate_return(rid: str):
    require_role("CustomerService")
    r = resolvers.ret(rid)
    return_logic.escalate_return(r, g.user_id)
    return success(_serialize(r))


@bp.route("/api/returns/<rid>/reopen", methods=["POST"])
def reopen_return(rid: str):
    require_role("CustomerService")
    r = resolvers.ret(rid)
    return_logic.reopen_return(r)
    return success(_serialize(r))
