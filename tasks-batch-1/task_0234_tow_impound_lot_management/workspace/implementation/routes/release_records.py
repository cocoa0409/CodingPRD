"""ReleaseRecord endpoints (nested under tow orders)."""
from flask import Blueprint

import db
from clock import iso, now
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services.serialize import public
from validators import paginate_and_respond, require_int, require_str, sort_by_created

bp = Blueprint("release_records", __name__)


def get_order_or_404(order_id):
    o = db.tow_orders.get(order_id)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    return o


@bp.route("/tow-orders/<order_id>/release-records", methods=["POST"])
def create_release(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    o = get_order_or_404(order_id)
    body = get_json_body()
    amount_paid = require_int(body, "amount_paid_cents", minimum=0)
    released_to_name = require_str(body, "released_to_name")
    if o["status"] != "RELEASE_AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", "Order is not RELEASE_AUTHORIZED")
    if o["hold_status"] != "NONE":
        raise ApiError("ERR_HOLD_ACTIVE", "An active hold blocks release")
    record = {
        "tow_order_id": order_id,
        "amount_paid_cents": amount_paid,
        "released_to_name": released_to_name,
        "authorized_at": iso(now()),
    }
    db.stamp_create(record)
    db.release_records[record["id"]] = record
    o["amount_paid_cents"] += amount_paid
    o["status"] = "RELEASED"
    db.touch(o)
    return object_response(public(record), 201)


@bp.route("/tow-orders/<order_id>/release-records", methods=["GET"])
def list_releases(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    get_order_or_404(order_id)
    items = [r for r in db.release_records.values() if r["tow_order_id"] == order_id]
    items = sort_by_created(items)
    return paginate_and_respond([public(r) for r in items])
