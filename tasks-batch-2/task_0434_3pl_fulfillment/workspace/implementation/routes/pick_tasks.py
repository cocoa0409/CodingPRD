"""PickTask endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import store, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_pick_task, get_lot, get_bin,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_pick_task

bp = Blueprint("pick_tasks", __name__)

READ_ROLES = {"PickOperator", "WavePlanner", "PackStation"}


@bp.route("/pick-tasks", methods=["GET"])
def list_pick_tasks():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.pick_tasks.values())
    for key in ("order_id", "lot_id", "sku_id"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, meta = paginate(items, limit, offset)
    return success([serialize_pick_task(r) for r in page], pagination=meta)


@bp.route("/pick-tasks/<pick_task_id>", methods=["GET"])
def get_one_pick_task(pick_task_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_pick_task(pick_task_id)
    return success(serialize_pick_task(rec))


@bp.route("/clients/<client_id>/pick-tasks/<pick_task_id>/confirm", methods=["POST"])
def confirm_pick(client_id, pick_task_id):
    _, role = get_auth()
    require_roles(role, {"PickOperator"})
    get_client(client_id)
    pt = get_pick_task(pick_task_id)
    body = get_json_body()

    if pt["status"] != "ASSIGNED":
        raise err("ERR_PICK_NOT_ASSIGNED", "Pick task is not ASSIGNED")

    # Owning bin of the task's lot must be OPEN.
    lot = store.inventory_lots.get(pt["lot_id"])
    if lot is not None:
        bin_rec = store.bins.get(lot["bin_id"])
        if bin_rec is not None and bin_rec["status"] != "OPEN":
            raise err("ERR_BIN_BLOCKED", "Owning bin is BLOCKED")

    picked_qty = body.get("picked_qty")
    if isinstance(picked_qty, bool) or not isinstance(picked_qty, int):
        raise err("ERR_INVALID_REQUEST", "picked_qty must be an integer")
    if picked_qty < 0 or picked_qty > pt["qty"]:
        raise err("ERR_INVALID_REQUEST", "picked_qty out of range")

    pt["picked_qty"] = picked_qty
    pt["status"] = "PICKED"
    touch(pt)
    return success(serialize_pick_task(pt))
