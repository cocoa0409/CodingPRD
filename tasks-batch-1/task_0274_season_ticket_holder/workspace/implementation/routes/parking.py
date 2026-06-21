"""ParkingAddOn: create (draw from zone capacity), fetch, list."""
from flask import Blueprint, request

import db
from errors import err
from helpers import (
    get_json_body,
    get_or_404,
    paginate,
    parking_addon_view,
    require_str,
)
from middleware import get_auth, require_role
from response import success, success_list

bp = Blueprint("parking", __name__)

ALL_ROLES = {"BoxOfficeAgent", "AccountHolder", "FinanceClerk"}


@bp.route("/parking-addons", methods=["POST"])
def create_parking_addon():
    user_id, role = get_auth()
    require_role(role, {"BoxOfficeAgent", "AccountHolder"})
    body = get_json_body()
    subscription_id = require_str(body, "subscription_id")
    parking_zone_id = require_str(body, "parking_zone_id")
    with db.lock:
        sub = db.subscriptions.get(subscription_id)
        if sub is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "subscription_id not found")
        zone = db.parking_zones.get(parking_zone_id)
        if zone is None:
            raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "parking_zone_id not found")

        # AccountHolder may only add on a subscription they own.
        if role == "AccountHolder" and sub["account_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Holder does not own this subscription")

        # Capacity check.
        active = sum(
            1
            for p in db.parking_addons.values()
            if p["parking_zone_id"] == parking_zone_id and p["status"] == "ACTIVE"
        )
        if active >= zone["capacity"]:
            raise err("ERR_PARKING_ZONE_FULL", "Parking zone is at capacity")

        row = db.new_common()
        row.update(
            {
                "subscription_id": subscription_id,
                "parking_zone_id": parking_zone_id,
                "price_cents": zone["price_cents"],
                "status": "ACTIVE",
            }
        )
        db.parking_addons[row["id"]] = row
        db.touch(zone)
        return success(parking_addon_view(row), 201)


@bp.route("/parking-addons/<rid>", methods=["GET"])
def get_parking_addon(rid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        row = get_or_404(db.parking_addons, rid)
        return success(parking_addon_view(row))


@bp.route("/parking-addons", methods=["GET"])
def list_parking_addons():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    subscription_id = request.args.get("subscription_id")
    parking_zone_id = request.args.get("parking_zone_id")
    status = request.args.get("status")
    with db.lock:
        rows = [
            p
            for p in db.parking_addons.values()
            if (subscription_id is None or p["subscription_id"] == subscription_id)
            and (parking_zone_id is None or p["parking_zone_id"] == parking_zone_id)
            and (status is None or p["status"] == status)
        ]
        page, limit, offset, total = paginate(rows)
        return success_list([parking_addon_view(r) for r in page], limit, offset, total)
