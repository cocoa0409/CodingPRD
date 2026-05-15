"""Hall / FloorPlan / Booth routes (§3.2)."""

from flask import Blueprint, g, request

import db
import response as resp
from middleware import require_roles
from services import hall_service
from services.common import must_exist, serialize


bp = Blueprint("halls", __name__)


@bp.route("/exhibitions/<exhibition_id>/halls", methods=["POST"])
def create_hall(exhibition_id):
    require_roles("VenueAdmin")
    row = hall_service.create_hall(exhibition_id, g.body)
    return resp.created(serialize(row))


@bp.route("/halls/<hall_id>/floor-plans", methods=["POST"])
def create_floor_plan(hall_id):
    require_roles("VenueAdmin")
    row = hall_service.create_floor_plan(hall_id, g.body)
    return resp.created(serialize(row))


@bp.route("/halls/<hall_id>/floor-plans/<plan_id>/activate", methods=["POST"])
def activate_floor_plan(hall_id, plan_id):
    require_roles("VenueAdmin")
    row = hall_service.activate_floor_plan(hall_id, plan_id, g.body)
    return resp.success(serialize(row))


@bp.route("/halls/<hall_id>/booths", methods=["POST"])
def create_booth(hall_id):
    require_roles("VenueAdmin")
    row = hall_service.create_booth(hall_id, g.body)
    return resp.created(serialize(row))


@bp.route("/halls/<hall_id>/booths", methods=["GET"])
def list_booths(hall_id):
    require_roles("VenueAdmin", "VenueOps", "Exhibitor")
    status = request.args.get("status")
    limit, offset = resp.parse_pagination(request.args)
    items, total = hall_service.list_booths_in_hall(hall_id, status, limit, offset)
    return resp.success_list([serialize(i) for i in items], total, limit, offset)


@bp.route("/booths/<booth_id>", methods=["GET"])
def get_booth(booth_id):
    require_roles("VenueAdmin", "VenueOps", "Exhibitor")
    booth = hall_service.get_booth(booth_id)
    return resp.success(serialize(booth))
