"""Truck endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_json_body,
    paginate,
    parse_pagination,
    require_number,
    require_string,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("trucks", __name__)


def get_truck_or_404(truck_id: str) -> dict:
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Truck id does not exist")
    return truck


@bp.route("/trucks", methods=["POST"])
@require_roles("WarehouseChief")
def create_truck(_user_id: str, _role: str):
    body = get_json_body()
    plate_no = require_string(body, "plate_no")
    capacity_kg = require_number(body, "capacity_kg", minimum=0, exclusive_min=True)

    for truck in db.trucks.values():
        if truck["plate_no"] == plate_no:
            raise_err(ERR_INVALID_REQUEST, "plate_no already registered")

    truck = {"plate_no": plate_no, "capacity_kg": capacity_kg}
    db.stamp_new(truck)
    db.trucks[truck["id"]] = truck
    return success_object(serialize(truck), 201)


@bp.route("/trucks/<truck_id>", methods=["GET"])
@require_roles("Any")
def get_truck(truck_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_truck_or_404(truck_id)))


@bp.route("/trucks/<truck_id>/load-schedules", methods=["GET"])
@require_roles("Any")
def list_truck_schedules(truck_id: str, _user_id: str, _role: str):
    get_truck_or_404(truck_id)
    limit, offset = parse_pagination()
    items = [s for s in db.load_schedules.values() if s["truck_id"] == truck_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
