"""FittingRoom endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import common
import services
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")

bp = Blueprint("fitting_rooms", __name__)


@bp.route("/fitting-rooms", methods=["POST"])
@require_roles("ShopManager")
def create_room():
    body = common.get_body()
    room_label = common.as_str(body, "room_label")
    capacity = common.as_int(body, "capacity", minimum=1)
    out_of_service = common.as_bool(body, "out_of_service", required=False, default=False)
    obj = {
        "id": db.new_id(),
        "room_label": room_label,
        "capacity": capacity,
        "out_of_service": out_of_service,
    }
    db.stamp_create(obj)
    db.fitting_rooms[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/fitting-rooms", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_rooms():
    limit, offset = common.paginate(request.args)
    window, meta = common.page_slice(list(db.fitting_rooms.values()), limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/fitting-rooms/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_room(rid):
    obj = services.get_fitting_room(rid)
    return success(common.serialize(obj))
