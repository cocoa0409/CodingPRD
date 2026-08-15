"""Switch order endpoints: get and list (system-driven lifecycle)."""

from flask import Blueprint, request

from db import STORE, public
from errors import raise_err, ERR_NOT_FOUND
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated

bp = Blueprint("switch_orders", __name__)


@bp.route("/transload/switch-orders/<sid>", methods=["GET"])
def get_switch_order(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    sw = STORE.switch_orders.get(sid)
    if sw is None:
        raise_err(ERR_NOT_FOUND, "switch order id does not exist")
    return ok(public(sw))


@bp.route("/transload/switch-orders", methods=["GET"])
def list_switch_orders():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    track_id = request.args.get("track_id")
    railcar_id = request.args.get("railcar_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = sorted(STORE.switch_orders.values(), key=lambda s: (s["created_at"], s["_seq"]))
    if track_id is not None:
        items = [s for s in items if s["track_id"] == track_id]
    if railcar_id is not None:
        items = [s for s in items if s["railcar_id"] == railcar_id]
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginated(items)
    return ok([public(s) for s in page], pagination=meta)
