"""VehicleClass endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from pagination import paginate
from response import array_response, object_response

bp = Blueprint("vehicle_classes", __name__)


@bp.route("/vehicle-classes", methods=["POST"])
def create_vehicle_class():
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    body = request.get_json(silent=True) or {}

    code = util.require_str(body, "code")
    tier_rank = util.require_int(body, "tier_rank", minimum=1)
    daily = util.require_int(body, "daily_rate_cents", minimum=1)
    weekly = util.require_int(body, "weekly_rate_cents", minimum=1)
    included = util.require_int(body, "included_miles_per_day", minimum=0)
    overage = util.require_int(body, "overage_per_mile_cents", minimum=0)
    ldw = util.require_int(body, "ldw_per_day_cents", minimum=0)
    pai = util.require_int(body, "pai_per_day_cents", minimum=0)

    for existing in db.vehicle_classes.values():
        if existing["code"] == code:
            raise err("ERR_INVALID_REQUEST", "VehicleClass code already exists: %s" % code)
        if existing["tier_rank"] == tier_rank:
            raise err(
                "ERR_INVALID_REQUEST",
                "VehicleClass tier_rank already exists: %s" % tier_rank,
            )

    rec = util.stamp_new(
        {
            "code": code,
            "tier_rank": tier_rank,
            "daily_rate_cents": daily,
            "weekly_rate_cents": weekly,
            "included_miles_per_day": included,
            "overage_per_mile_cents": overage,
            "ldw_per_day_cents": ldw,
            "pai_per_day_cents": pai,
        }
    )
    db.vehicle_classes[rec["id"]] = rec
    return object_response(serialize.vehicle_class(rec), 201)


@bp.route("/vehicle-classes/<class_id>", methods=["GET"])
def get_vehicle_class(class_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    rec = lookup.get_vehicle_class(class_id)
    return object_response(serialize.vehicle_class(rec), 200)


@bp.route("/vehicle-classes/<class_id>/vehicles", methods=["GET"])
def list_class_vehicles(class_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})
    lookup.get_vehicle_class(class_id)

    status = request.args.get("status")
    location_id = request.args.get("location_id")
    matches = [
        v
        for v in db.vehicles.values()
        if v["class_id"] == class_id
        and (status is None or v["status"] == status)
        and (location_id is None or v["location_id"] == location_id)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.vehicle(v) for v in page], limit, offset, total, 200
    )
