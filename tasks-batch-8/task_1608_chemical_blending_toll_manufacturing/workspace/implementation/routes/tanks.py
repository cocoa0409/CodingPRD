"""Tank endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_tank,
    to_int,
)
from services.calculations import ZONES

bp = Blueprint("tanks", __name__)


def _tank_or_404(tid):
    t = db.tanks.get(tid)
    if t is None:
        raise errors.not_found("tank not found")
    return t


@bp.route("/toll-operations/tanks", methods=["POST"])
def create_tank():
    require_role({"QualityManager"})
    body = request.get_json(silent=True) or {}
    tank_code = body.get("tank_code")
    if not tank_code or not isinstance(tank_code, str):
        raise errors.invalid_request("tank_code required")
    capacity_l = to_int(body.get("capacity_l"), "capacity_l")
    if capacity_l <= 0:
        raise errors.invalid_request("capacity_l must be > 0")
    working_capacity_l = to_int(body.get("working_capacity_l"), "working_capacity_l")
    if working_capacity_l <= 0 or working_capacity_l > capacity_l:
        raise errors.invalid_request("working_capacity_l must be in (0, capacity_l]")
    current_zone = body.get("current_zone")
    if current_zone not in ZONES:
        raise errors.invalid_request("current_zone invalid")

    now = now_iso()
    tid = new_id()
    tank = {
        "id": tid,
        "tank_code": tank_code,
        "capacity_l": capacity_l,
        "working_capacity_l": working_capacity_l,
        "current_zone": current_zone,
        "occupied_by_batch_id": None,
        "last_product_ghs": None,
        "cleaning_state": "DIRTY",
        "operational_state": "AVAILABLE",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.tanks[tid] = tank
    return success_object(serialize_tank(tank), status=201)


@bp.route("/toll-operations/tanks", methods=["GET"])
def list_tanks():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = list(db.tanks.values())
    ob = request.args.get("occupied_by_batch_id")
    if ob is not None:
        rows = [t for t in rows if t.get("occupied_by_batch_id") == ob]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_tank(t) for t in slice_], limit, offset, total)


@bp.route("/toll-operations/tanks/<id>", methods=["GET"])
def get_tank(id):
    require_role({"Any"})
    t = _tank_or_404(id)
    return success_object(serialize_tank(t))
